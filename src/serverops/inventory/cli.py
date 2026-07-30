"""Inventory transform CLI commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Annotated

import typer

from serverops.inventory import transformer
from serverops.paths import (
    data_path,
    decrypted_inventory_output_path,
    encrypted_inventory_output_path,
    inventory_path,
)
from serverops.vault import VaultError, create_vault_client, decrypt_inventory, encrypt_inventory

app = typer.Typer(help="Transform Tailscale and Coolify inventories.")

DEFAULT_TAILSCALE = inventory_path("tailscale-inventory.yaml")
DEFAULT_COOLIFY = inventory_path("coolify-inventory.yaml")
DEFAULT_DASHBOARD_DIR = data_path("transformed", "dashboard")
DEFAULT_TEMPLATE_DIR = data_path("transformed", "templates")


@app.command("dashboard")
def dashboard(
    tailscale: Annotated[
        Path,
        typer.Option(help="Tailscale inventory path."),
    ] = DEFAULT_TAILSCALE,
    coolify: Annotated[
        Path,
        typer.Option(help="Coolify inventory path."),
    ] = DEFAULT_COOLIFY,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o"),
    ] = DEFAULT_DASHBOARD_DIR,
    format: Annotated[str, typer.Option()] = "yaml",
) -> None:
    """Create dashboard-oriented Tailnet and Coolify datasets."""
    args = argparse.Namespace(
        command="dashboard",
        tailscale=tailscale,
        coolify=coolify,
        output_dir=output_dir,
        format=format,
    )
    try:
        outputs = transformer.dashboard_command(args)
    except (OSError, transformer.TransformError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Wrote {len(outputs)} file(s):")
    for path in outputs:
        typer.echo(f"  {path}")


@app.command("template")
def template(
    coolify: Annotated[
        Path,
        typer.Option(help="Coolify inventory path."),
    ] = DEFAULT_COOLIFY,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o"),
    ] = DEFAULT_TEMPLATE_DIR,
    overwrite: Annotated[bool, typer.Option("--overwrite")] = False,
) -> None:
    """Organize Coolify Compose definitions into a template workspace."""
    args = argparse.Namespace(
        command="template",
        coolify=coolify,
        output_dir=output_dir,
        overwrite=overwrite,
    )
    try:
        outputs = transformer.template_command(args)
    except (OSError, transformer.TransformError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Wrote {len(outputs)} file(s):")
    for path in outputs:
        typer.echo(f"  {path}")


# ---------------------------------------------------------------------------
# Vault Transit encrypt / decrypt
# ---------------------------------------------------------------------------

_VAULT_ADDR_HELP = (
    "Vault server address (overrides VAULT_ADDR env var). Example: https://vault.example.com:8200"
)
_VAULT_TOKEN_HELP = (
    "Vault token (overrides VAULT_TOKEN env var). "
    "Prefer AppRole or environment variables to avoid shell-history exposure."
)
_VAULT_ROLE_ID_HELP = "AppRole role ID (overrides VAULT_ROLE_ID env var)."
_VAULT_SECRET_ID_HELP = (
    "AppRole secret ID (overrides VAULT_SECRET_ID env var). "
    "Prefer environment variables or credential files."
)


def _vault_client(
    vault_addr: str | None,
    vault_token: str | None,
    vault_role_id: str | None,
    vault_secret_id: str | None,
):
    try:
        return create_vault_client(
            vault_addr=vault_addr,
            vault_token=vault_token,
            role_id=vault_role_id,
            secret_id=vault_secret_id,
        )
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("encrypt")
def encrypt(
    file: Annotated[Path, typer.Argument(help="Inventory file to encrypt (YAML or JSON).")],
    vault_addr: Annotated[str | None, typer.Option("--vault-addr", help=_VAULT_ADDR_HELP)] = None,
    vault_token: Annotated[
        str | None,
        typer.Option("--vault-token", help=_VAULT_TOKEN_HELP, hide_input=True),
    ] = None,
    vault_role_id: Annotated[
        str | None,
        typer.Option("--vault-role-id", help=_VAULT_ROLE_ID_HELP, hide_input=True),
    ] = None,
    vault_secret_id: Annotated[
        str | None,
        typer.Option("--vault-secret-id", help=_VAULT_SECRET_ID_HELP, hide_input=True),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="Output path (default: data/encrypted/inventory/<basename>.enc)",
        ),
    ] = None,
) -> None:
    """Encrypt an inventory file with the Vault Transit engine.

    Ciphertext is written under ``data/encrypted/inventory/`` (or ``--output``).
    The original plaintext file is NOT deleted.  This is a read-only transform.
    """
    if not file.exists():
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)

    client = _vault_client(vault_addr, vault_token, vault_role_id, vault_secret_id)
    out_path = output or encrypted_inventory_output_path(file)

    data = file.read_bytes()
    try:
        ciphertext = encrypt_inventory(client, data)
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ciphertext + "\n", encoding="utf-8")
    typer.echo(f"Encrypted {file} -> {out_path}")


@app.command("decrypt")
def decrypt(
    file: Annotated[Path, typer.Argument(help="Encrypted file produced by 'encrypt'.")],
    vault_addr: Annotated[str | None, typer.Option("--vault-addr", help=_VAULT_ADDR_HELP)] = None,
    vault_token: Annotated[
        str | None,
        typer.Option("--vault-token", help=_VAULT_TOKEN_HELP, hide_input=True),
    ] = None,
    vault_role_id: Annotated[
        str | None,
        typer.Option("--vault-role-id", help=_VAULT_ROLE_ID_HELP, hide_input=True),
    ] = None,
    vault_secret_id: Annotated[
        str | None,
        typer.Option("--vault-secret-id", help=_VAULT_SECRET_ID_HELP, hide_input=True),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="Output path (default: data/inventory/<basename without .enc>)",
        ),
    ] = None,
) -> None:
    """Decrypt a Vault-encrypted inventory file.

    Plaintext is written under ``data/inventory/`` (or ``--output``).
    This is a read-only transform.
    """
    if not file.exists():
        typer.echo(f"Error: file not found: {file}", err=True)
        raise typer.Exit(1)

    client = _vault_client(vault_addr, vault_token, vault_role_id, vault_secret_id)
    out_path = output or decrypted_inventory_output_path(file)

    ciphertext = file.read_text(encoding="utf-8").strip()
    try:
        plaintext = decrypt_inventory(client, ciphertext)
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(plaintext)
    typer.echo(f"Decrypted {file} -> {out_path}")
