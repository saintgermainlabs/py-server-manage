"""On-server backup preflight checks (read-only)."""

from __future__ import annotations

import shutil
import socket
from pathlib import Path
from typing import Any

from serverops.backup.credentials import load_credentials_env, load_passphrase_file
from serverops.backup.models import BackupConfigModel
from serverops.models import Status, Target
from serverops.utils.command import run_read_only
from serverops.utils.filesystem import path_probe
from serverops.utils.secrets import redact_value


def run_preflight(
    config: BackupConfigModel,
    *,
    target: Target,
    timeout: int,
    check_storage_box: bool = True,
    require_credentials: bool = False,
) -> dict[str, Any]:
    """Validate tools, paths, and optional Storage Box TCP reachability.

    When ``require_credentials`` is true (mutating apply paths), missing SSH key
    or credentials file are errors rather than warnings.
    """
    checks: list[dict[str, Any]] = []
    cred_status = Status.ERROR if require_credentials else Status.WARNING

    for tool, binary in (
        ("borg", "borg"),
        ("borgmatic", "borgmatic"),
        ("docker", "docker"),
    ):
        path = shutil.which(binary)
        checks.append(
            _check(
                name=f"tool:{tool}",
                status=Status.OK if path else Status.ERROR,
                summary=f"Found {path}" if path else f"{binary} not on PATH",
                evidence={"path": path},
            )
        )

    for path in (
        *config.mandatory_sources,
        config.staging_directory,
        config.restore_directory,
    ):
        probe = path_probe(path)
        # Staging/restore may be missing until install --apply.
        if path in {config.staging_directory, config.restore_directory}:
            status = (
                Status.OK
                if probe["status"] == "ok"
                else Status.WARNING
                if probe["status"] == "missing"
                else Status.ERROR
            )
            summary = probe["summary"]
            if probe["status"] == "missing":
                summary = f"Not created yet (run install --apply): {path}"
        else:
            status = (
                Status.OK
                if probe["status"] == "ok"
                else Status.WARNING
                if probe["status"] in {"missing", "skipped"}
                else Status.ERROR
            )
            summary = probe["summary"]
        checks.append(
            _check(
                name=f"path:{path}",
                status=status,
                summary=summary,
                evidence=probe,
            )
        )

    key = Path(config.repository.ssh_key)
    try:
        key_exists = key.exists()
    except OSError as exc:
        checks.append(
            _check(
                name="ssh_key",
                status=cred_status,
                summary=f"Cannot access SSH key path {key}: {exc}",
                evidence={"path": str(key)},
            )
        )
        key_exists = False
    else:
        if key_exists:
            checks.append(
                _check(
                    name="ssh_key",
                    status=Status.OK,
                    summary=f"SSH key present: {key}",
                    evidence={"path": str(key)},
                )
            )
        else:
            checks.append(
                _check(
                    name="ssh_key",
                    status=cred_status,
                    summary=f"SSH key missing (create on server): {key}",
                    evidence={"path": str(key)},
                )
            )

    creds = Path(config.deploy.credentials_file)
    try:
        creds_exists = creds.exists()
    except OSError as exc:
        checks.append(
            _check(
                name="credentials_file",
                status=cred_status,
                summary=f"Cannot access credentials path {creds}: {exc}",
                evidence={"path": str(creds)},
            )
        )
        creds_exists = False
    else:
        if creds_exists:
            checks.append(
                _check(
                    name="credentials_file",
                    status=Status.OK,
                    summary=f"Credentials file exists: {creds}",
                    evidence={"path": str(creds)},
                )
            )
        else:
            checks.append(
                _check(
                    name="credentials_file",
                    status=cred_status,
                    summary=f"Credentials file not found yet: {creds}",
                    evidence={"path": str(creds)},
                )
            )

    if (
        require_credentials
        and not config.repository.is_placeholder()
        and key_exists
        and creds_exists
    ):
        try:
            file_env = load_credentials_env(creds)
            passphrase = file_env.get(config.repository.passphrase_environment_variable, "").strip()
            if not passphrase:
                passphrase = load_passphrase_file(config.repository.passphrase_file)
            if not passphrase:
                checks.append(
                    _check(
                        name="passphrase",
                        status=Status.ERROR,
                        summary=(
                            f"{config.repository.passphrase_environment_variable} "
                            "missing or empty in credentials file and "
                            f"{config.repository.passphrase_file} is empty or missing"
                        ),
                        evidence={"path": str(creds)},
                    )
                )
            else:
                checks.append(
                    _check(
                        name="passphrase",
                        status=Status.OK,
                        summary="Borg passphrase is available locally",
                        evidence={"path": str(creds)},
                    )
                )
        except OSError as exc:
            checks.append(
                _check(
                    name="passphrase",
                    status=Status.ERROR,
                    summary=f"Cannot read credentials file: {exc}",
                    evidence={"path": str(creds)},
                )
            )

    try:
        docker = run_read_only(
            ["docker", "version", "--format", "{{.Server.Version}}"],
            target=target,
            timeout=timeout,
        )
        checks.append(
            _check(
                name="docker_daemon",
                status=Status.OK if docker.returncode == 0 else Status.WARNING,
                summary=(
                    f"Docker server {docker.stdout}"
                    if docker.returncode == 0
                    else (docker.stderr or "docker version failed")
                ),
                evidence={"returncode": docker.returncode},
            )
        )
    except (OSError, PermissionError, ValueError) as exc:
        checks.append(
            _check(
                name="docker_daemon",
                status=Status.WARNING,
                summary=str(exc),
                evidence={},
            )
        )

    if check_storage_box:
        checks.append(_storage_box_check(config, timeout=timeout))

    errors = sum(1 for item in checks if item["status"] == Status.ERROR.value)
    warnings = sum(1 for item in checks if item["status"] == Status.WARNING.value)
    return redact_value(
        {
            "schema_version": 1,
            "ok": errors == 0,
            "error_count": errors,
            "warning_count": warnings,
            "repository_placeholder": config.repository.is_placeholder(),
            "require_credentials": require_credentials,
            "checks": checks,
        }
    )


def _storage_box_check(config: BackupConfigModel, *, timeout: int) -> dict[str, Any]:
    if config.repository.is_placeholder():
        return _check(
            name="storage_box_tcp",
            status=Status.SKIPPED,
            summary="Repository URL still uses STORAGE_HOST/STORAGE_USER placeholders",
            evidence={"url": config.repository.url},
        )
    host, port = config.repository.host_port()
    if not host:
        return _check(
            name="storage_box_tcp",
            status=Status.ERROR,
            summary="Could not parse Storage Box hostname from repository URL",
            evidence={"url": config.repository.url},
        )
    try:
        with socket.create_connection((host, port), timeout=min(timeout, 10)):
            return _check(
                name="storage_box_tcp",
                status=Status.OK,
                summary=f"TCP connect succeeded to {host}:{port}",
                evidence={"host": host, "port": port},
            )
    except OSError as exc:
        return _check(
            name="storage_box_tcp",
            status=Status.ERROR,
            summary=f"TCP connect failed to {host}:{port}: {exc}",
            evidence={"host": host, "port": port},
        )


def _check(
    *,
    name: str,
    status: Status,
    summary: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": name,
        "status": status.value,
        "summary": summary,
        "evidence": evidence,
    }
