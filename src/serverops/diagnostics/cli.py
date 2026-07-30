"""Debugging and host diagnostic CLI commands."""

from __future__ import annotations

from typing import Annotated

import typer
from rich.table import Table

from serverops.app_state import console, emit, state
from serverops.diagnostics.host import host_checks
from serverops.runner import run_command

app = typer.Typer(help="Read-only host and Docker diagnostics.")
host_app = typer.Typer(help="Inspect local or SSH hosts.")
docker_app = typer.Typer(help="Inspect Docker workloads.")
app.add_typer(host_app, name="host")
app.add_typer(docker_app, name="docker")


@app.command("doctor")
def doctor() -> None:
    """Run safe host diagnostics."""
    results = host_checks(state.target, state.config.command_timeout_seconds)
    if state.json_output:
        emit([result.model_dump(mode="json") for result in results])
        return
    table = Table("Check", "Status", "Summary")
    for result in results:
        table.add_row(result.name, result.status.value, result.summary)
    console.print(table)


@host_app.command("run")
def host_run(
    command: Annotated[list[str], typer.Argument(help="Allowlisted read-only command")],
) -> None:
    """Run a read-only diagnostic command."""
    emit(
        run_command(
            command,
            target=state.target,
            timeout=state.config.command_timeout_seconds,
        )
    )


@docker_app.command("ps")
def docker_ps(all_containers: Annotated[bool, typer.Option("--all", "-a")] = False) -> None:
    """List containers."""
    argv = ["docker", "ps", "--format", "json"]
    if all_containers:
        argv.append("--all")
    emit(run_command(argv, target=state.target, timeout=state.config.command_timeout_seconds))


@docker_app.command("logs")
def docker_logs(
    container: str,
    tail: Annotated[int, typer.Option(min=1, max=5000)] = 200,
) -> None:
    """Read recent container logs."""
    emit(
        run_command(
            ["docker", "logs", "--tail", str(tail), container],
            target=state.target,
            timeout=state.config.command_timeout_seconds,
        )
    )
