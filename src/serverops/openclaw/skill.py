"""Locate the OpenClaw skill package shipped with this repository."""

from __future__ import annotations

from pathlib import Path

from serverops.paths import REPO_ROOT


def skill_path() -> Path:
    """Return the path to the OpenClaw skill markdown file."""
    return REPO_ROOT / "openclaw" / "serverops" / "SKILL.md"


def skill_dir() -> Path:
    """Return the OpenClaw skill directory."""
    return skill_path().parent
