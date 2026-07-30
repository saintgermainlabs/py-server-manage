"""Tests for Tailscale CLI binary resolution."""

from __future__ import annotations

from pathlib import Path

from serverops.tailscale.inventory import resolve_tailscale_binary


def test_resolve_absolute_executable(tmp_path: Path) -> None:
    binary = tmp_path / "tailscale"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")
    binary.chmod(0o755)
    assert resolve_tailscale_binary(str(binary)) == str(binary)


def test_resolve_absolute_missing_returns_none(tmp_path: Path) -> None:
    assert resolve_tailscale_binary(str(tmp_path / "missing")) is None
