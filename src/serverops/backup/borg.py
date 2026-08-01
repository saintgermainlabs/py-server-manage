"""Borg/borgmatic integration for repository init, create, list, and check."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from serverops.backup.credentials import load_credentials_env
from serverops.backup.models import BackupConfigModel
from serverops.models import CommandResult, Target
from serverops.runner import run_command
from serverops.utils.secrets import REDACTED, redact_text, redact_value


class BorgError(RuntimeError):
    """Raised when a Borg/borgmatic operation fails or is misconfigured."""


CommandRunner = Callable[..., CommandResult]


def default_command_runner(
    argv: list[str],
    *,
    target: Target,
    timeout: int,
    allow_mutation: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    return run_command(
        argv,
        target=target,
        timeout=timeout,
        allow_mutation=allow_mutation,
        env=env,
    )


def repository_url_ok(config: BackupConfigModel) -> None:
    if config.repository.is_placeholder():
        raise BorgError(
            "Repository URL still uses STORAGE_USER/STORAGE_HOST placeholders; "
            "edit the live backup config on the server first."
        )


def ssh_command_for(config: BackupConfigModel) -> str:
    return f"ssh -i {config.repository.ssh_key} -p 23 -o BatchMode=yes"


def build_borg_env(
    config: BackupConfigModel,
    *,
    require_passphrase: bool = True,
) -> dict[str, str]:
    """Build child process env with passphrase and BORG_RSH; never log values."""
    env = dict(os.environ)
    file_env = load_credentials_env(config.deploy.credentials_file)
    env.update(file_env)
    passphrase_key = config.repository.passphrase_environment_variable
    passphrase = env.get(passphrase_key, "").strip()
    if require_passphrase and not passphrase:
        raise BorgError(
            f"{passphrase_key} is missing or empty (set it in {config.deploy.credentials_file})"
        )
    env["BORG_RSH"] = ssh_command_for(config)
    env["BORG_UNKNOWN_UNENCRYPTED_REPO_ACCESS_IS_OK"] = "no"
    env["BORG_RELOCATED_REPO_ACCESS_IS_OK"] = "no"
    return env


def secret_values_from_env(env: Mapping[str, str], config: BackupConfigModel) -> list[str]:
    values: list[str] = []
    passphrase = env.get(config.repository.passphrase_environment_variable, "")
    if passphrase:
        values.append(passphrase)
    return values


def scrub_output(text: str, secrets: Sequence[str]) -> str:
    cleaned = redact_text(text)
    for secret in secrets:
        if secret and len(secret) >= 4:
            cleaned = cleaned.replace(secret, REDACTED)
    return cleaned


def _redact_result(
    result: CommandResult,
    secrets: Sequence[str],
) -> CommandResult:
    return CommandResult(
        argv=result.argv,
        returncode=result.returncode,
        stdout=scrub_output(result.stdout, secrets),
        stderr=scrub_output(result.stderr, secrets),
        duration_seconds=result.duration_seconds,
    )


def _run(
    argv: list[str],
    *,
    config: BackupConfigModel,
    target: Target,
    timeout: int,
    allow_mutation: bool,
    runner: CommandRunner,
    require_passphrase: bool = True,
) -> CommandResult:
    repository_url_ok(config)
    env = build_borg_env(config, require_passphrase=require_passphrase)
    secrets = secret_values_from_env(env, config)
    try:
        result = runner(
            argv,
            target=target,
            timeout=timeout,
            allow_mutation=allow_mutation,
            env=env,
        )
    except TypeError:
        # Test fakes may omit env=.
        result = runner(
            argv,
            target=target,
            timeout=timeout,
            allow_mutation=allow_mutation,
        )
    return _redact_result(result, secrets)


def init_repository(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int,
    dry_run: bool = True,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Initialize an encrypted Borg repository on the Storage Box."""
    repository_url_ok(config)
    argv = [
        "borg",
        "init",
        "--encryption=repokey-blake2",
        config.repository.url,
    ]
    if dry_run:
        return redact_value(
            {
                "ok": True,
                "dry_run": True,
                "action": "init",
                "argv": argv,
                "summary": "Would initialize Borg repository (dry-run)",
            }
        )
    key = Path(config.repository.ssh_key)
    if not key.is_file():
        raise BorgError(f"SSH key not found: {key}")
    active_runner = runner or default_command_runner
    result = _run(
        argv,
        config=config,
        target=target,
        timeout=timeout,
        allow_mutation=True,
        runner=active_runner,
    )
    ok = result.returncode == 0
    return redact_value(
        {
            "ok": ok,
            "dry_run": False,
            "action": "init",
            "argv": result.argv,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "summary": (
                "Borg repository initialized"
                if ok
                else (result.stderr or result.stdout or "borg init failed")
            ),
        }
    )


def create_archive(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int,
    dry_run: bool = True,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Create a files archive via borgmatic."""
    repository_url_ok(config)
    borgmatic_config = config.deploy.borgmatic_config
    argv = ["borgmatic", "create", "--config", borgmatic_config]
    if dry_run:
        preview = [*argv, "--dry-run"]
        return redact_value(
            {
                "ok": True,
                "dry_run": True,
                "action": "create",
                "argv": preview,
                "summary": "Would run borgmatic create (dry-run; no archive written)",
            }
        )
    active_runner = runner or default_command_runner
    result = _run(
        argv,
        config=config,
        target=target,
        timeout=timeout,
        allow_mutation=True,
        runner=active_runner,
    )
    ok = result.returncode == 0
    return redact_value(
        {
            "ok": ok,
            "dry_run": False,
            "action": "create",
            "argv": result.argv,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "summary": (
                "Archive created"
                if ok
                else (result.stderr or result.stdout or "borgmatic create failed")
            ),
        }
    )


def list_archives(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """List archives in the configured repository."""
    repository_url_ok(config)
    argv = ["borgmatic", "list", "--config", config.deploy.borgmatic_config]
    active_runner = runner or default_command_runner
    result = _run(
        argv,
        config=config,
        target=target,
        timeout=timeout,
        allow_mutation=False,
        runner=active_runner,
    )
    ok = result.returncode == 0
    return redact_value(
        {
            "ok": ok,
            "action": "list",
            "argv": result.argv,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "summary": "Listed archives" if ok else (result.stderr or "borgmatic list failed"),
        }
    )


def check_repository(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int,
    full: bool = False,
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    """Run a repository check (lightweight by default)."""
    repository_url_ok(config)
    argv = ["borgmatic", "check", "--config", config.deploy.borgmatic_config]
    if not full:
        argv.extend(["--only", "repository"])
    active_runner = runner or default_command_runner
    result = _run(
        argv,
        config=config,
        target=target,
        timeout=timeout,
        allow_mutation=False,
        runner=active_runner,
    )
    ok = result.returncode == 0
    return redact_value(
        {
            "ok": ok,
            "action": "check",
            "full": full,
            "argv": result.argv,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_seconds": result.duration_seconds,
            "summary": "Repository check ok" if ok else (result.stderr or "borgmatic check failed"),
        }
    )
