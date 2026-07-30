"""Filesystem helpers for discovery and reports."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def path_probe(path: Path | str) -> dict[str, Any]:
    """Return a read-only probe of a filesystem path."""
    target = Path(path)
    result: dict[str, Any] = {
        "path": str(target),
        "exists": False,
        "is_dir": False,
        "is_file": False,
        "is_symlink": False,
        "readable": False,
        "size_bytes": None,
        "mode": None,
        "status": "missing",
        "summary": f"Path not found: {target}",
    }
    try:
        exists = target.exists()
    except OSError as exc:
        result["status"] = "skipped"
        result["summary"] = f"Cannot access path: {exc}"
        return result
    result["exists"] = exists
    if not exists:
        return result
    try:
        result["is_symlink"] = target.is_symlink()
        result["is_dir"] = target.is_dir()
        result["is_file"] = target.is_file()
        result["readable"] = os.access(target, os.R_OK)
        stat = target.stat(follow_symlinks=False)
        result["mode"] = oct(stat.st_mode & 0o777)
        if result["is_file"]:
            result["size_bytes"] = stat.st_size
        if result["readable"]:
            result["status"] = "ok"
            result["summary"] = f"Accessible {'directory' if result['is_dir'] else 'file'}"
        else:
            result["status"] = "skipped"
            result["summary"] = "Exists but not readable with current privileges"
    except OSError as exc:
        result["status"] = "error"
        result["summary"] = f"Could not inspect path: {exc}"
    return result


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
