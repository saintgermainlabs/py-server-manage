"""Install plan and apply logic for on-server backup scaffolding."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any, Literal

from serverops.backup.generate import generate_configs
from serverops.backup.models import BackupConfigModel
from serverops.utils.filesystem import ensure_parent

ActionKind = Literal["mkdir", "copy", "chmod", "package", "note"]


def build_install_plan(
    config: BackupConfigModel,
    *,
    generated_dir: Path,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Return ordered install actions (no side effects)."""
    deploy = config.deploy
    actions: list[dict[str, Any]] = []

    binary_for_package = {
        "borgbackup": "borg",
        "borgmatic": "borgmatic",
    }
    for package in deploy.packages:
        binary = binary_for_package.get(package, package)
        actions.append(
            {
                "kind": "package",
                "name": package,
                "present": shutil.which(binary) is not None,
                "summary": f"Ensure package/tool available: {package} ({binary})",
            }
        )

    for directory in (
        deploy.config_dir,
        str(Path(deploy.borgmatic_config).parent),
        config.staging_directory,
        config.restore_directory,
    ):
        actions.append(
            {
                "kind": "mkdir",
                "path": directory,
                "summary": f"Create directory {directory}",
            }
        )

    mappings = [
        (generated_dir / "backup.yaml", Path(deploy.config_dir) / "backup.yaml"),
        (
            generated_dir / "credentials.env.example",
            Path(deploy.credentials_file),
        ),
        (generated_dir / "borgmatic.yaml", Path(deploy.borgmatic_config)),
        (
            generated_dir / "server-backup.service",
            Path(deploy.systemd_dir) / "server-backup.service",
        ),
        (
            generated_dir / "server-backup.timer",
            Path(deploy.systemd_dir) / "server-backup.timer",
        ),
        (
            generated_dir / "server-backup-check.service",
            Path(deploy.systemd_dir) / "server-backup-check.service",
        ),
        (
            generated_dir / "server-backup-check.timer",
            Path(deploy.systemd_dir) / "server-backup-check.timer",
        ),
    ]

    for source, destination in mappings:
        exists = destination.exists()
        blocked = exists and not force and destination.name != "credentials.env"
        # credentials.env: never overwrite if exists unless force
        if destination.name == Path(deploy.credentials_file).name and exists and not force:
            blocked = True
        actions.append(
            {
                "kind": "copy",
                "source": str(source),
                "destination": str(destination),
                "exists": exists,
                "blocked": blocked,
                "summary": (
                    f"Copy {source.name} → {destination}"
                    + (" (blocked: exists, use --force)" if blocked else "")
                ),
            }
        )

    actions.append(
        {
            "kind": "chmod",
            "path": deploy.credentials_file,
            "mode": 0o600,
            "summary": f"chmod 0600 {deploy.credentials_file}",
        }
    )
    actions.append(
        {
            "kind": "note",
            "summary": (
                "Generate/authorize SSH key at "
                f"{config.repository.ssh_key} on this host; do not enable timers "
                "until preflight passes and Storage Box URL is real."
            ),
        }
    )
    return actions


def apply_install_plan(
    plan: list[dict[str, Any]],
    *,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Execute or preview an install plan."""
    performed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[str] = []

    for action in plan:
        kind = action["kind"]
        if kind == "note" or kind == "package":
            performed.append({**action, "result": "recorded"})
            continue
        if kind == "mkdir":
            path = Path(action["path"])
            if dry_run:
                performed.append({**action, "result": "dry-run"})
                continue
            try:
                path.mkdir(parents=True, exist_ok=True)
                performed.append({**action, "result": "created"})
            except OSError as exc:
                errors.append(f"mkdir {path}: {exc}")
            continue
        if kind == "copy":
            if action.get("blocked"):
                skipped.append({**action, "result": "skipped"})
                continue
            source = Path(action["source"])
            destination = Path(action["destination"])
            if not source.is_file():
                errors.append(f"missing generated file: {source}")
                continue
            if dry_run:
                performed.append({**action, "result": "dry-run"})
                continue
            try:
                ensure_parent(destination)
                if destination.name.endswith(".env") and not destination.exists():
                    # Install example content as credentials.env starter.
                    shutil.copyfile(source, destination)
                elif destination.name == "credentials.env":
                    shutil.copyfile(source, destination)
                else:
                    shutil.copyfile(source, destination)
                performed.append({**action, "result": "copied"})
            except OSError as exc:
                errors.append(f"copy {destination}: {exc}")
            continue
        if kind == "chmod":
            path = Path(action["path"])
            if dry_run:
                performed.append({**action, "result": "dry-run"})
                continue
            if not path.exists():
                skipped.append({**action, "result": "skipped-missing"})
                continue
            try:
                os.chmod(path, int(action["mode"]))
                performed.append({**action, "result": "chmod"})
            except OSError as exc:
                errors.append(f"chmod {path}: {exc}")
            continue

    return {
        "dry_run": dry_run,
        "performed": performed,
        "skipped": skipped,
        "errors": errors,
        "ok": not errors,
    }


def install_backup_system(
    config: BackupConfigModel,
    *,
    dry_run: bool = True,
    force: bool = False,
    generated_dir: Path | None = None,
) -> dict[str, Any]:
    """Generate configs if needed, then dry-run or apply the install plan."""
    from serverops.backup.generate import default_output_dir

    output = generated_dir or default_output_dir()
    written = generate_configs(config, output_dir=output)
    plan = build_install_plan(config, generated_dir=output, force=force)
    result = apply_install_plan(plan, dry_run=dry_run)
    result["generated"] = {key: str(path) for key, path in written.items()}
    result["plan"] = plan
    return result
