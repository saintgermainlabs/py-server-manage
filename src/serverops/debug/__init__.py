"""Compatibility shim — prefer ``serverops.diagnostics``."""

from serverops.diagnostics import host_checks
from serverops.diagnostics.cli import app, docker_app, host_app

__all__ = ["app", "docker_app", "host_app", "host_checks"]
