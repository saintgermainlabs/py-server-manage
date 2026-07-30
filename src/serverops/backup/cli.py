"""Backup CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from serverops.app_state import emit, state
from serverops.backup import discovery, inventory
from serverops.backup.config import BackupConfigError, load_backup_config
from serverops.backup.generate import default_output_dir, generate_configs
from serverops.backup.install import install_backup_system
from serverops.backup.preflight import run_preflight

app = typer.Typer(help="Host-level backup discovery and on-server Borg scaffolding.")


def _not_ready(name: str) -> None:
    typer.echo(
        f"`serverops backup {name}` is not implemented yet "
        "(needs Storage Box init / dump pipeline).",
        err=True,
    )
    raise typer.Exit(code=2)


@app.command("discover")
def discover_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Optional backup YAML config path."),
    ] = None,
) -> None:
    """Read-only discovery of mandatory paths, Docker, and Coolify recovery items."""
    try:
        backup_config = load_backup_config(config)
        result = discovery.discover(
            target=state.target,
            timeout=state.config.command_timeout_seconds,
            config=backup_config,
        )
        written = {
            **inventory.write_backup_inventory(result),
            **{
                f"system_{key}": value
                for key, value in inventory.write_system_state(result).items()
            },
        }
    except (BackupConfigError, OSError, PermissionError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(
            {
                "summary": result.get("summary"),
                "review_notes": result.get("review_notes"),
                "files": {key: str(path) for key, path in written.items()},
            }
        )
        return

    summary = result.get("summary") or {}
    typer.echo(
        "Backup discovery complete: "
        f"{summary.get('mandatory_paths_ok')}/{summary.get('mandatory_paths_total')} "
        "mandatory paths ready, "
        f"{summary.get('probable_databases')} probable databases."
    )
    for key, path in written.items():
        typer.echo(f"  {key}: {path}")


@app.command("inventory")
def inventory_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Optional backup YAML config path."),
    ] = None,
) -> None:
    """Alias for discover — write backup inventory artifacts."""
    discover_cmd(config=config)


@app.command("validate-config")
def validate_config(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
) -> None:
    """Validate backup configuration models."""
    try:
        model = load_backup_config(config)
    except BackupConfigError as exc:
        typer.echo(f"Invalid backup config: {exc}", err=True)
        raise typer.Exit(1) from exc
    if state.json_output:
        emit(model.model_dump())
    else:
        typer.echo("Backup config OK")


@app.command("generate-config")
def generate_config_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
    output_dir: Annotated[
        Path | None,
        typer.Option("--output-dir", "-o", help="Staging directory for generated files."),
    ] = None,
) -> None:
    """Write staged borgmatic/systemd/credentials files under data/backups/generated/."""
    try:
        backup_config = load_backup_config(config)
        written = generate_configs(backup_config, output_dir=output_dir)
    except (BackupConfigError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    if state.json_output:
        emit({key: str(path) for key, path in written.items()})
        return
    typer.echo(f"Wrote {len(written)} file(s) to {output_dir or default_output_dir()}:")
    for key, path in written.items():
        typer.echo(f"  {key}: {path}")


@app.command("install")
def install_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--apply", help="Preview by default; --apply writes files."),
    ] = True,
    force: Annotated[
        bool,
        typer.Option("--force", help="Allow overwriting existing live config files."),
    ] = False,
    generated_dir: Annotated[
        Path | None,
        typer.Option(help="Directory of generated configs (default: data/backups/generated)."),
    ] = None,
) -> None:
    """Install backup scaffolding on this host (dry-run by default)."""
    try:
        backup_config = load_backup_config(config)
        result = install_backup_system(
            backup_config,
            dry_run=dry_run,
            force=force,
            generated_dir=generated_dir,
        )
    except (BackupConfigError, OSError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(result)
    else:
        mode = "DRY-RUN" if dry_run else "APPLY"
        typer.echo(f"Backup install ({mode}): ok={result['ok']}")
        for action in result.get("plan") or []:
            typer.echo(f"  - {action.get('summary')}")
        for item in result.get("skipped") or []:
            typer.echo(f"  skipped: {item.get('summary')}")
        for err in result.get("errors") or []:
            typer.echo(f"  error: {err}", err=True)
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("preflight")
def preflight_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
    skip_storage_box: Annotated[
        bool,
        typer.Option("--skip-storage-box", help="Skip TCP check to Storage Box."),
    ] = False,
) -> None:
    """Run on-server preflight checks (read-only)."""
    try:
        backup_config = load_backup_config(config)
        result = run_preflight(
            backup_config,
            target=state.target,
            timeout=state.config.command_timeout_seconds,
            check_storage_box=not skip_storage_box,
        )
    except (BackupConfigError, OSError, PermissionError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(result)
    else:
        typer.echo(
            f"Preflight ok={result['ok']} "
            f"errors={result['error_count']} warnings={result['warning_count']}"
        )
        for check in result.get("checks") or []:
            typer.echo(f"  [{check['status']}] {check['name']}: {check['summary']}")
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("run")
def run_cmd() -> None:
    """Run a backup (not implemented yet)."""
    _not_ready("run")


@app.command("check")
def check_cmd() -> None:
    """Repository check (not implemented yet)."""
    _not_ready("check")


@app.command("list")
def list_cmd() -> None:
    """List archives (not implemented yet)."""
    _not_ready("list")


@app.command("restore")
def restore_cmd() -> None:
    """Restore into a temporary directory (not implemented yet)."""
    _not_ready("restore")


@app.command("restore-test")
def restore_test_cmd() -> None:
    """Isolated restore test (not implemented yet)."""
    _not_ready("restore-test")


@app.command("status")
def status_cmd() -> None:
    """Show backup status (not implemented yet)."""
    _not_ready("status")


@app.command("report")
def report_cmd() -> None:
    """Emit backup report (not implemented yet)."""
    _not_ready("report")
