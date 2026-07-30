"""Coolify path and recovery-item probes for backup discovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from serverops.utils.filesystem import path_probe
from serverops.utils.secrets import redact_value

COOLIFY_ROOT = Path("/data/coolify")
CRITICAL_RELATIVE = (
    "source/.env",
    "ssh/keys",
    "source/docker-compose.custom.yml",
)


def discover_coolify() -> dict[str, Any]:
    """Probe Coolify recovery paths on the local filesystem."""
    root = path_probe(COOLIFY_ROOT)
    critical = []
    for relative in CRITICAL_RELATIVE:
        probe = path_probe(COOLIFY_ROOT / relative)
        probe["relative"] = relative
        probe["critical"] = True
        critical.append(probe)
    return redact_value(
        {
            "root": root,
            "critical_items": critical,
            "notes": [
                "Coolify APP_KEY in source/.env is required to decrypt restored DB fields.",
                "Coolify SSH keys are required to reconnect managed servers.",
            ],
        }
    )
