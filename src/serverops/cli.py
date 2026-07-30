"""Root ServerOps CLI that composes feature modules."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer

from serverops.app_state import state
from serverops.backup.cli import app as backup_app
from serverops.config import load_config
from serverops.coolify.cli import app as coolify_app
from serverops.diagnostics.cli import app as diagnostics_app
from serverops.diagnostics.cli import docker_app, host_app
from serverops.inventory.cli import app as inventory_app
from serverops.openclaw.cli import app as openclaw_app
from serverops.tailscale.cli import app as tailscale_app

app = typer.Typer(
    no_args_is_help=True,
    help="Safe, modular operations toolkit for backups, Coolify, Tailscale, and hosts.",
)

app.add_typer(backup_app, name="backup")
app.add_typer(tailscale_app, name="tailscale")
app.add_typer(coolify_app, name="coolify")
app.add_typer(diagnostics_app, name="diagnostics")
app.add_typer(diagnostics_app, name="debug")  # compatibility alias
app.add_typer(openclaw_app, name="openclaw")
app.add_typer(inventory_app, name="inventory")
app.add_typer(host_app, name="host")
app.add_typer(docker_app, name="docker")


@app.callback()
def main(
    config: Annotated[Path | None, typer.Option(envvar="SERVEROPS_CONFIG")] = None,
    target: Annotated[str | None, typer.Option(help="Named target from config")] = None,
    json_output: Annotated[bool, typer.Option("--json", help="Machine-readable output")] = False,
) -> None:
    if config is None:
        config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        preferred = config_home / "py-server-manage" / "config.yaml"
        legacy = config_home / "serverops" / "config.yaml"
        config = preferred if preferred.exists() or not legacy.exists() else legacy
    state.config, state.secrets = load_config(config)
    target_name = target or state.config.default_target
    if target_name not in state.config.targets:
        raise typer.BadParameter(f"Unknown target: {target_name}")
    state.target = state.config.targets[target_name]
    state.json_output = json_output


@app.command("doctor")
def doctor() -> None:
    """Run safe host diagnostics (alias for `diagnostics doctor`)."""
    from serverops.diagnostics.cli import doctor as diagnostics_doctor

    diagnostics_doctor()


if __name__ == "__main__":
    app()
