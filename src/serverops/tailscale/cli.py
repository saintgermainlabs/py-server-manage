"""Tailscale CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from serverops.paths import inventory_path
from serverops.tailscale import api_inventory, inventory, nodes

app = typer.Typer(help="Tailscale inventory and node helpers.")

DEFAULT_CLI_INVENTORY = inventory_path("tailscale-inventory.yaml")
DEFAULT_API_INVENTORY = inventory_path("tailscale-api-inventory.yaml")
DEFAULT_NODES = inventory_path("tailscale-api-nodes.yaml")


@app.command("inventory")
def inventory_cmd(
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output YAML path."),
    ] = DEFAULT_CLI_INVENTORY,
    tailscale_bin: Annotated[str, typer.Option("--tailscale-bin")] = "tailscale",
    timeout: Annotated[float, typer.Option(help="Per-command timeout seconds.")] = 5.0,
    ping_count: Annotated[int, typer.Option("--ping-count")] = 2,
    no_ping: Annotated[bool, typer.Option("--no-ping")] = False,
    workers: Annotated[int, typer.Option(help="Parallel node inspection workers.")] = 8,
) -> None:
    """Export a read-only Tailscale CLI inventory to YAML."""
    argv = [
        "--output",
        str(output),
        "--tailscale-bin",
        tailscale_bin,
        "--timeout",
        str(timeout),
        "--ping-count",
        str(ping_count),
        "--workers",
        str(workers),
    ]
    if no_ping:
        argv.append("--no-ping")
    raise SystemExit(inventory.main(argv))


@app.command("api-inventory")
def api_inventory_cmd(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output YAML/JSON path."),
    ] = None,
    tailnet: Annotated[
        str | None,
        typer.Option(help='Tailnet id, or "-" for the token default.'),
    ] = None,
    format: Annotated[str, typer.Option(help="yaml or json.")] = "yaml",
    profile: Annotated[
        str,
        typer.Option(help="Output profile: verbose or dashboard."),
    ] = "verbose",
    dashboard_config: Annotated[
        Path | None,
        typer.Option(
            "--dashboard-config",
            help="Optional YAML/JSON app overrides for the dashboard profile.",
        ),
    ] = None,
    only_ui: Annotated[
        bool,
        typer.Option(
            "--only-ui",
            help="Dashboard only: include only devices with UI overrides.",
        ),
    ] = False,
    no_details: Annotated[bool, typer.Option("--no-details")] = False,
    include_logs: Annotated[bool, typer.Option("--include-logs")] = False,
    workers: Annotated[int, typer.Option()] = 8,
) -> None:
    """Export a Tailscale API inventory (requires TAILSCALE_API_KEY)."""
    argv = ["--profile", profile, "--format", format, "--workers", str(workers)]
    if output is not None:
        argv.extend(["--output", str(output)])
    if tailnet is not None:
        argv.extend(["--tailnet", tailnet])
    if dashboard_config is not None:
        argv.extend(["--dashboard-config", str(dashboard_config)])
    if only_ui:
        argv.append("--only-ui")
    if no_details:
        argv.append("--no-details")
    if include_logs:
        argv.append("--include-logs")
    raise SystemExit(api_inventory.main(argv))


@app.command("nodes")
def nodes_cmd(
    inventory_file: Annotated[
        Path,
        typer.Argument(help="API inventory file to parse."),
    ] = DEFAULT_API_INVENTORY,
    output: Annotated[
        Path,
        typer.Option("--output", "-o"),
    ] = DEFAULT_NODES,
    format: Annotated[str, typer.Option()] = "yaml",
) -> None:
    """Parse an API inventory into a nodes-only file (no users)."""
    raise SystemExit(
        nodes.main(
            [
                str(inventory_file),
                "--output",
                str(output),
                "--format",
                format,
            ]
        )
    )
