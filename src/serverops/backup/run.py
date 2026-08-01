"""Backup run and init workflows (files-only; DB dumps later)."""

from __future__ import annotations

import contextlib
import fcntl
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from serverops.backup import borg
from serverops.backup.borg import CommandRunner
from serverops.backup.models import BackupConfigModel, utc_now
from serverops.backup.preflight import run_preflight
from serverops.models import Status, Target
from serverops.utils.secrets import redact_value


class BackupLockError(RuntimeError):
    """Raised when another backup run holds the lock."""


class BackupRunError(RuntimeError):
    """Raised for configuration or policy failures before execution."""


@contextmanager
def acquire_backup_lock(lock_file: str) -> Iterator[None]:
    path = Path(lock_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(fd)
        raise BackupLockError(f"Backup lock held: {path}") from exc
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def require_mutations_allowed(allow_mutations: bool, *, apply: bool) -> None:
    if apply and not allow_mutations:
        raise BackupRunError(
            "Mutations are disabled (allow_mutations: false). "
            "Set allow_mutations: true in ~/.config/py-server-manage/config.yaml "
            "on the backup host before using --apply."
        )


def require_ready_for_apply(config: BackupConfigModel) -> None:
    """Fail closed when credentials or key are missing for mutating ops."""
    borg.repository_url_ok(config)
    key = Path(config.repository.ssh_key)
    if not key.is_file():
        raise BackupRunError(f"SSH key missing: {key}")
    creds = Path(config.deploy.credentials_file)
    if not creds.is_file():
        raise BackupRunError(f"Credentials file missing: {creds}")
    # Validate passphrase without exposing it.
    borg.build_borg_env(config, require_passphrase=True)


def init_backup_repository(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int,
    dry_run: bool = True,
    allow_mutations: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    require_mutations_allowed(allow_mutations, apply=not dry_run)
    if not dry_run:
        require_ready_for_apply(config)
    result = borg.init_repository(
        config,
        target=target,
        timeout=timeout,
        dry_run=dry_run,
        runner=runner,
    )
    return redact_value({**result, "generated_at": utc_now()})


def run_backup(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int | None = None,
    dry_run: bool = True,
    allow_mutations: bool = False,
    skip_storage_box: bool = False,
    runner: CommandRunner | None = None,
    preflight_fn: Any | None = None,
) -> dict[str, Any]:
    """Run files-only backup workflow; dry-run by default."""
    require_mutations_allowed(allow_mutations, apply=not dry_run)
    effective_timeout = timeout if timeout is not None else 300
    steps: list[dict[str, Any]] = []
    notes: list[str] = []

    if config.repository.is_placeholder():
        raise BackupRunError("Repository URL still uses STORAGE_USER/STORAGE_HOST placeholders")

    if not dry_run:
        require_ready_for_apply(config)

    def _preflight() -> dict[str, Any]:
        fn = preflight_fn or run_preflight
        return fn(
            config,
            target=target,
            timeout=min(effective_timeout, 60),
            check_storage_box=not skip_storage_box,
            require_credentials=not dry_run,
        )

    if dry_run:
        preflight = _preflight()
        steps.append({"name": "preflight", "result": preflight})
        if preflight.get("error_count", 0) > 0:
            return _report(
                ok=False,
                dry_run=True,
                steps=steps,
                notes=notes,
                summary="Preflight reported errors; refusing dry-run plan",
            )
        if True:  # files-only: no database dump pipeline yet
            notes.append("databases: [] — skipping native dumps (files-only backup)")
        create = borg.create_archive(
            config,
            target=target,
            timeout=effective_timeout,
            dry_run=True,
            runner=runner,
        )
        steps.append({"name": "create", "result": create})
        if True:  # lightweight check after create (default)
            steps.append(
                {
                    "name": "check",
                    "result": {
                        "ok": True,
                        "dry_run": True,
                        "summary": "Would run lightweight repository check after create",
                    },
                }
            )
        return _report(
            ok=True,
            dry_run=True,
            steps=steps,
            notes=notes,
            summary="Dry-run plan complete; re-run with --apply to create an archive",
        )

    with acquire_backup_lock(config.lock_file):
        preflight = _preflight()
        steps.append({"name": "preflight", "result": preflight})
        if not preflight.get("ok"):
            return _report(
                ok=False,
                dry_run=False,
                steps=steps,
                notes=notes,
                summary="Preflight failed; backup aborted",
            )

        Path(config.staging_directory).mkdir(parents=True, exist_ok=True)
        steps.append(
            {
                "name": "staging",
                "result": {
                    "ok": True,
                    "summary": f"Staging directory ready: {config.staging_directory}",
                },
            }
        )

        if True:  # files-only: no database dump pipeline yet
            notes.append("databases: [] — skipping native dumps (files-only backup)")
        else:
            notes.append(
                "Database dump pipeline not implemented yet; configured databases were skipped"
            )

        create = borg.create_archive(
            config,
            target=target,
            timeout=effective_timeout,
            dry_run=False,
            runner=runner,
        )
        steps.append({"name": "create", "result": create})
        if not create.get("ok"):
            return _report(
                ok=False,
                dry_run=False,
                steps=steps,
                notes=notes,
                summary=create.get("summary") or "Archive create failed",
            )

        check_result: dict[str, Any] | None = None
        if True:  # lightweight check after create (default)
            check_result = borg.check_repository(
                config,
                target=target,
                timeout=effective_timeout,
                full=False,
                runner=runner,
            )
            steps.append({"name": "check", "result": check_result})
            if not check_result.get("ok"):
                return _report(
                    ok=False,
                    dry_run=False,
                    steps=steps,
                    notes=notes,
                    summary=check_result.get("summary") or "Repository check failed",
                )

        # Clear staging contents after success (keep directory).
        _clear_staging(config.staging_directory)
        steps.append(
            {
                "name": "cleanup_staging",
                "result": {"ok": True, "summary": "Staging cleared after success"},
            }
        )

        return _report(
            ok=True,
            dry_run=False,
            steps=steps,
            notes=notes,
            summary="Files-only backup completed successfully",
        )


def _clear_staging(staging_directory: str) -> None:
    root = Path(staging_directory)
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            with contextlib.suppress(OSError):
                child.unlink()


def _report(
    *,
    ok: bool,
    dry_run: bool,
    steps: list[dict[str, Any]],
    notes: list[str],
    summary: str,
) -> dict[str, Any]:
    return redact_value(
        {
            "schema_version": 1,
            "ok": ok,
            "dry_run": dry_run,
            "generated_at": utc_now(),
            "summary": summary,
            "notes": notes,
            "steps": steps,
            "status": Status.OK.value if ok else Status.ERROR.value,
        }
    )
