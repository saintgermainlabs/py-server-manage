"""Command helpers wrapping the shared runner with redaction support."""

from __future__ import annotations

from serverops.models import CommandResult, Target
from serverops.runner import run_command
from serverops.utils.secrets import redact_text


def run_read_only(
    argv: list[str],
    *,
    target: Target,
    timeout: int,
) -> CommandResult:
    """Run an allowlisted read-only command and redact captured streams."""
    result = run_command(argv, target=target, timeout=timeout)
    return CommandResult(
        argv=result.argv,
        returncode=result.returncode,
        stdout=redact_text(result.stdout),
        stderr=redact_text(result.stderr),
        duration_seconds=result.duration_seconds,
    )
