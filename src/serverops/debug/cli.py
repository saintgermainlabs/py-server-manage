"""Compatibility CLI re-export."""

from serverops.diagnostics.cli import app, docker_app, doctor, host_app

__all__ = ["app", "docker_app", "doctor", "host_app"]
