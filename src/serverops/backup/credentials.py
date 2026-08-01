"""Load backup EnvironmentFile credentials without logging values."""

from __future__ import annotations

from pathlib import Path


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
