"""Coolify CLI commands."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer

from serverops.app_state import emit, state
from serverops.coolify import inventory as coolify_inventory
from serverops.coolify.client import CoolifyClient
from serverops.paths import inventory_path

app = typer.Typer(help="Coolify API and inventory commands.")

DEFAULT_INVENTORY = inventory_path("coolify-inventory.yaml")


def _client() -> CoolifyClient:
    cfg = state.config.coolify
    token = (
        state.secrets.coolify_token
        or os.environ.get("COOLIFY_API_KEY")
        or os.environ.get("COOLIFY_API_TOKEN")
        or os.environ.get("COOLIFY_TOKEN")
    )
    base_url = cfg.base_url or os.environ.get("COOLIFY_URL")
    if not base_url:
        raise typer.BadParameter("Set coolify.base_url in config or COOLIFY_URL in the environment")
    return CoolifyClient(base_url, token, verify_tls=cfg.verify_tls)


@app.command("inventory")
def inventory_cmd(
    output: Annotated[
        Path,
        typer.Option("--output", "-o"),
    ] = DEFAULT_INVENTORY,
    url: Annotated[
        str | None,
        typer.Option(help="Coolify base URL (or COOLIFY_URL)."),
    ] = None,
    api_key: Annotated[
        str | None,
        typer.Option("--api-key", help="API token (or COOLIFY_API_KEY)."),
    ] = None,
    include_sensitive: Annotated[bool, typer.Option("--include-sensitive")] = False,
    strict: Annotated[bool, typer.Option("--strict")] = False,
) -> None:
    """Export a detailed Coolify inventory to YAML/JSON."""
    argv = ["--output", str(output)]
    if url:
        argv.extend(["--url", url])
    if api_key:
        argv.extend(["--api-key", api_key])
    if include_sensitive:
        argv.append("--include-sensitive")
    if strict:
        argv.append("--strict")
    if not os.environ.get("COOLIFY_API_KEY"):
        for alias in ("COOLIFY_API_TOKEN", "COOLIFY_TOKEN"):
            if os.environ.get(alias):
                os.environ["COOLIFY_API_KEY"] = os.environ[alias]
                break
    raise SystemExit(coolify_inventory.main(argv))


@app.command("health")
def health() -> None:
    """Check the public Coolify health endpoint."""
    emit(_client().health())


@app.command("get")
def get(path: Annotated[str, typer.Argument(help="API v1 path, e.g. /servers")]) -> None:
    """Make an authenticated read-only Coolify API request."""
    emit(_client().request("GET", path))


@app.command("request")
def request(
    method: Annotated[str, typer.Argument()],
    path: Annotated[str, typer.Argument()],
    data: Annotated[str | None, typer.Option(help="JSON request body")] = None,
    apply: Annotated[bool, typer.Option(help="Actually send a mutating request")] = False,
) -> None:
    """Preview or issue a Coolify API request."""
    method = method.upper()
    payload = json.loads(data) if data else None
    if method != "GET" and not apply:
        emit({"dry_run": True, "method": method, "path": path, "payload": payload})
        return
    if method != "GET" and not state.config.allow_mutations:
        raise typer.BadParameter("Mutations are disabled by allow_mutations: false")
    emit(_client().request(method, path, payload=payload))
