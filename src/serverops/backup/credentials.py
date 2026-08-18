"""Load backup EnvironmentFile credentials without logging values."""

from __future__ import annotations

from pathlib import Path

from serverops.backup.models import BackupConfigModel


def load_credentials_env(path: Path | str) -> dict[str, str]:
    """Parse KEY=value lines from a credentials file (systemd EnvironmentFile style)."""
    candidate = Path(path)
    if not candidate.is_file():
        return {}
    parsed: dict[str, str] = {}
    for raw_line in candidate.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            parsed[key] = value
    return parsed


def load_passphrase_file(path: Path | str) -> str:
    """Return stripped passphrase file contents; empty if missing."""
    candidate = Path(path)
    if not candidate.is_file():
        return ""
    return candidate.read_text(encoding="utf-8").strip()


def resolve_passphrase(config: BackupConfigModel) -> str:
    """Resolve Borg passphrase from credentials.env, then the Agent-rendered file."""
    key = config.repository.passphrase_environment_variable
    from_env_file = load_credentials_env(config.deploy.credentials_file).get(key, "").strip()
    if from_env_file:
        return from_env_file
    return load_passphrase_file(config.repository.passphrase_file)
