"""OpenClaw integration CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer

from serverops.app_state import emit, state
from serverops.diagnostics.host import host_checks
from serverops.openclaw.skill import skill_dir, skill_path

app = typer.Typer(help="OpenClaw skill helpers and read-only diagnostics.")


@app.command("skill")
def skill(
    show: Annotated[
        bool,
        typer.Option("--show", help="Print the skill markdown contents."),
    ] = False,
) -> None:
    """Show the OpenClaw skill path (and optionally its contents)."""
    path = skill_path()
    payload = {
        "skill_path": str(path),
        "skill_dir": str(skill_dir()),
        "exists": path.is_file(),
    }
    if show and path.is_file():
        payload["contents"] = path.read_text(encoding="utf-8")
    emit(payload)


@app.command("doctor")
def doctor() -> None:
    """Run the same read-only host doctor OpenClaw should prefer first."""
    results = host_checks(state.target, state.config.command_timeout_seconds)
    emit([result.model_dump(mode="json") for result in results])
