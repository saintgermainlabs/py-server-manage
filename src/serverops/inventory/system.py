"""System inventory probes for backup discovery."""

from __future__ import annotations

import platform
import shutil
import socket
from typing import Any

from serverops.models import Target
from serverops.utils.command import run_read_only
from serverops.utils.secrets import redact_value

TOOL_CANDIDATES = (
    "borg",
    "borgmatic",
    "docker",
    "pg_dump",
    "mysqldump",
    "mariadb-dump",
    "mongodump",
    "redis-cli",
)


def discover_system(target: Target, timeout: int) -> dict[str, Any]:
    """Collect lightweight host state without secrets."""
    tools = {name: shutil.which(name) for name in TOOL_CANDIDATES}
    state: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "tools": {name: path for name, path in tools.items() if path},
        "missing_tools": sorted(name for name, path in tools.items() if not path),
        "commands": {},
        "warnings": [],
    }

    probes = {
        "uname": ["uname", "-a"],
        "disk": ["df", "-hT"],
        "memory": ["free", "-h"],
        "block_devices": ["lsblk", "-o", "NAME,SIZE,TYPE,MOUNTPOINTS,FSTYPE"],
    }
    for name, argv in probes.items():
        try:
            result = run_read_only(argv, target=target, timeout=timeout)
            state["commands"][name] = {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            if result.returncode != 0:
                state["warnings"].append(f"{name}: {result.stderr or 'failed'}")
        except (OSError, PermissionError, ValueError) as exc:
            state["warnings"].append(f"{name}: {exc}")
            state["commands"][name] = {"ok": False, "error": str(exc)}

    return redact_value(state)
