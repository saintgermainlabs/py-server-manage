"""Backup CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from serverops.app_state import emit, state
from serverops.backup import borg, discovery, inventory
from serverops.backup.config import BackupConfigError, load_backup_config
from serverops.backup.databases_config import (
    DEFAULT_DATABASES_PATH,
    EXAMPLE_DATABASES_PATH,
    DatabaseAllowlistError,
    load_database_allowlist,
    reconcile_allowlist_with_discovery,
)
from serverops.backup.generate import default_output_dir, generate_configs
from serverops.backup.install import install_backup_system
from serverops.backup.preflight import run_preflight
from serverops.backup.run import (
    BackupLockError,
    BackupRunError,
    init_backup_repository,
    run_backup,
)

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


@app.command("discover-databases")
def discover_databases_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Optional backup YAML config path."),
    ] = None,
    databases_file: Annotated[
        Path | None,
        typer.Option(
            help=(
                "Database allowlist path (default: /etc/server-backup/databases.yaml, "
                "else config/databases.example.yaml)."
            ),
        ),
    ] = None,
) -> None:
    """Read-only dry-run: list probable DB containers and compare to allowlist."""
    try:
        backup_config = load_backup_config(config)
        result = discovery.discover(
            target=state.target,
            timeout=state.config.command_timeout_seconds,
            config=backup_config,
        )
        plan = discovery.database_dump_plan(result)
        allowlist_path = databases_file
        if allowlist_path is None:
            deploy_path = Path(backup_config.deploy.databases_file)
            if deploy_path.is_file():
                allowlist_path = deploy_path
            elif DEFAULT_DATABASES_PATH.is_file():
                allowlist_path = DEFAULT_DATABASES_PATH
            elif EXAMPLE_DATABASES_PATH.is_file():
                allowlist_path = EXAMPLE_DATABASES_PATH
        allowlist = load_database_allowlist(allowlist_path)
        reconciliation = reconcile_allowlist_with_discovery(
            allowlist,
            list(result.get("databases") or []),
        )
        plan["allowlist_path"] = str(allowlist_path) if allowlist_path else None
        plan["allowlist"] = reconciliation
    except (
        BackupConfigError,
        DatabaseAllowlistError,
        OSError,
        PermissionError,
        ValueError,
    ) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(plan)
        return

    summary = plan.get("summary") or {}
    typer.echo(
        "Database discovery dry-run: "
        f"{summary.get('probable_databases')} probable, "
        f"{summary.get('would_native_dump')} would native-dump, "
        f"{summary.get('would_review')} need review "
        f"(docker_available={summary.get('docker_available')})."
    )
    if plan.get("allowlist_path"):
        typer.echo(f"Allowlist: {plan['allowlist_path']}")
    dumps = plan.get("would_native_dump") or []
    if dumps:
        typer.echo("Discovered — would native-dump (advisory):")
        for item in dumps:
            typer.echo(
                f"  - {item.get('stable_identity')} "
                f"[{item.get('engine')}] container={item.get('container')}"
            )
    reviews = plan.get("would_review") or []
    if reviews:
        typer.echo("Discovered — would review (not auto-dump):")
        for item in reviews:
            typer.echo(
                f"  - {item.get('stable_identity')} "
                f"[{item.get('engine')}] method={item.get('proposed_backup_method')} "
                f"container={item.get('container')}"
            )
    allow = plan.get("allowlist") or {}
    allow_summary = allow.get("summary") or {}
    if allow_summary:
        typer.echo(
            "Allowlist reconciliation: "
            f"{allow_summary.get('matched')} matched, "
            f"{allow_summary.get('missing_runtime')} missing at runtime, "
            f"{allow_summary.get('discovered_not_allowlisted')} discovered but not listed."
        )
    for note in plan.get("notes") or []:
        typer.echo(f"  note: {note}")


@app.command("build-databases-allowlist")
def build_databases_allowlist_cmd(
    backup_inventory: Annotated[
        Path | None,
        typer.Option(
            help="backup-inventory.yaml from `backup discover` "
            "(default: data/inventory/backup-inventory.yaml)."
        ),
    ] = None,
    coolify_inventory: Annotated[
        Path | None,
        typer.Option(
            help="Coolify inventory YAML (default: data/inventory/coolify-inventory.yaml)."
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "-o",
            "--output",
            help="Write path when using --apply (default: data/inventory/databases.yaml).",
        ),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run/--apply",
            help="Preview by default; --apply writes the allowlist YAML.",
        ),
    ] = True,
) -> None:
    """Build databases.yaml from inventories with Vault KV placeholders (no secrets)."""
    from serverops.backup.allowlist_build import (
        allowlist_to_yaml,
        build_databases_allowlist,
        load_yaml_mapping,
    )
    from serverops.paths import (
        DEFAULT_DATABASES_ALLOWLIST,
        inventory_path,
    )

    backup_path = backup_inventory or inventory_path("backup-inventory.yaml")
    coolify_path = coolify_inventory or inventory_path("coolify-inventory.yaml")
    out_path = output or DEFAULT_DATABASES_ALLOWLIST

    try:
        backup_data = load_yaml_mapping(backup_path) if backup_path.is_file() else None
        coolify_data = load_yaml_mapping(coolify_path) if coolify_path.is_file() else None
        if backup_data is None and coolify_data is None:
            raise FileNotFoundError(
                f"Need at least one inventory file "
                f"(tried {backup_path} and {coolify_path}). "
                "Decrypt Coolify inventory and/or run backup discover first."
            )
        allowlist, report = build_databases_allowlist(
            backup_inventory=backup_data,
            coolify_inventory=coolify_data,
        )
        yaml_text = allowlist_to_yaml(allowlist)
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    report["dry_run"] = dry_run
    report["output"] = str(out_path)
    report["entries"] = [
        {
            "id": e.id,
            "engine": e.engine,
            "dump": e.dump,
            "container_name": e.container_name,
            "coolify_uuid": e.coolify_uuid,
            "vault_path": e.vault.path if e.vault else None,
        }
        for e in allowlist.databases
    ]

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(yaml_text, encoding="utf-8")
        report["written"] = True

    if state.json_output:
        emit(report)
        return

    mode = "DRY-RUN" if dry_run else "APPLY"
    summary = report.get("summary") or {}
    typer.echo(
        f"Build databases allowlist ({mode}): "
        f"{summary.get('entries')} entries "
        f"(native={summary.get('native')}, skip={summary.get('skip')}) "
        f"sources={report.get('sources_used')}"
    )
    for entry in report.get("entries") or []:
        typer.echo(
            f"  - {entry.get('id')} [{entry.get('engine')}] "
            f"dump={entry.get('dump')} container={entry.get('container_name')} "
            f"uuid={entry.get('coolify_uuid')}"
        )
    if dry_run:
        typer.echo(f"Would write: {out_path}")
        typer.echo("Re-run with --apply to write, then:")
        typer.echo(f"  serverops inventory encrypt {out_path}")
    else:
        typer.echo(f"Wrote {out_path}")
        typer.echo(f"Encrypt: serverops inventory encrypt {out_path}")
    for note in report.get("notes") or []:
        typer.echo(f"  note: {note}")


@app.command("encrypt-databases")
def encrypt_databases_cmd(
    file: Annotated[
        Path | None,
        typer.Argument(help="Plaintext databases.yaml (default: data/inventory/databases.yaml)."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Ciphertext path."),
    ] = None,
    vault_addr: Annotated[str | None, typer.Option("--vault-addr")] = None,
    vault_token: Annotated[
        str | None,
        typer.Option("--vault-token", hide_input=True),
    ] = None,
    vault_role_id: Annotated[
        str | None,
        typer.Option("--vault-role-id", hide_input=True),
    ] = None,
    vault_secret_id: Annotated[
        str | None,
        typer.Option("--vault-secret-id", hide_input=True),
    ] = None,
) -> None:
    """Encrypt databases allowlist with Vault Transit (same as inventory encrypt)."""
    from serverops.paths import (
        DEFAULT_DATABASES_ALLOWLIST,
        DEFAULT_DATABASES_ALLOWLIST_ENC,
        encrypted_inventory_output_path,
    )
    from serverops.vault import VaultError, create_vault_client, encrypt_inventory

    source = file or DEFAULT_DATABASES_ALLOWLIST
    if not source.is_file():
        typer.echo(f"Error: file not found: {source}", err=True)
        raise typer.Exit(1)
    out_path = output or (
        DEFAULT_DATABASES_ALLOWLIST_ENC
        if source == DEFAULT_DATABASES_ALLOWLIST
        else encrypted_inventory_output_path(source)
    )
    try:
        client = create_vault_client(
            vault_addr=vault_addr,
            vault_token=vault_token,
            role_id=vault_role_id,
            secret_id=vault_secret_id,
        )
        ciphertext = encrypt_inventory(client, source.read_bytes())
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(ciphertext + "\n", encoding="utf-8")
    typer.echo(f"Encrypted {source} -> {out_path}")


@app.command("decrypt-databases")
def decrypt_databases_cmd(
    file: Annotated[
        Path | None,
        typer.Argument(
            help="Encrypted databases.yaml.enc "
            "(default: data/encrypted/inventory/databases.yaml.enc)."
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="Plaintext output path."),
    ] = None,
    vault_addr: Annotated[str | None, typer.Option("--vault-addr")] = None,
    vault_token: Annotated[
        str | None,
        typer.Option("--vault-token", hide_input=True),
    ] = None,
    vault_role_id: Annotated[
        str | None,
        typer.Option("--vault-role-id", hide_input=True),
    ] = None,
    vault_secret_id: Annotated[
        str | None,
        typer.Option("--vault-secret-id", hide_input=True),
    ] = None,
) -> None:
    """Decrypt databases allowlist with Vault Transit (same as inventory decrypt)."""
    from serverops.paths import (
        DEFAULT_DATABASES_ALLOWLIST,
        DEFAULT_DATABASES_ALLOWLIST_ENC,
        decrypted_inventory_output_path,
    )
    from serverops.vault import VaultError, create_vault_client, decrypt_inventory

    source = file or DEFAULT_DATABASES_ALLOWLIST_ENC
    if not source.is_file():
        typer.echo(f"Error: file not found: {source}", err=True)
        raise typer.Exit(1)
    out_path = output or (
        DEFAULT_DATABASES_ALLOWLIST
        if source == DEFAULT_DATABASES_ALLOWLIST_ENC
        else decrypted_inventory_output_path(source)
    )
    try:
        client = create_vault_client(
            vault_addr=vault_addr,
            vault_token=vault_token,
            role_id=vault_role_id,
            secret_id=vault_secret_id,
        )
        plaintext = decrypt_inventory(client, source.read_text(encoding="utf-8").strip())
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(plaintext)
    typer.echo(f"Decrypted {source} -> {out_path}")


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
    require_credentials: Annotated[
        bool,
        typer.Option(
            "--require-credentials",
            help="Treat missing SSH key/credentials/passphrase as errors.",
        ),
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
            require_credentials=require_credentials,
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


@app.command("init")
def init_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--apply", help="Preview by default; --apply runs borg init."),
    ] = True,
) -> None:
    """Initialize the encrypted Borg repository on the Storage Box."""
    try:
        backup_config = load_backup_config(config)
        result = init_backup_repository(
            backup_config,
            target=state.target,
            timeout=state.config.command_timeout_seconds,
            dry_run=dry_run,
            allow_mutations=state.config.allow_mutations,
        )
    except (
        BackupConfigError,
        BackupRunError,
        borg.BorgError,
        OSError,
        PermissionError,
        ValueError,
    ) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(result)
    else:
        mode = "DRY-RUN" if dry_run else "APPLY"
        typer.echo(f"Backup init ({mode}): ok={result.get('ok')} — {result.get('summary')}")
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("run")
def run_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run/--apply", help="Preview by default; --apply creates an archive."),
    ] = True,
    skip_storage_box: Annotated[
        bool,
        typer.Option("--skip-storage-box", help="Skip Storage Box TCP check during preflight."),
    ] = False,
) -> None:
    """Run a files-only backup (dry-run by default)."""
    try:
        backup_config = load_backup_config(config)
        result = run_backup(
            backup_config,
            target=state.target,
            timeout=state.config.command_timeout_seconds,
            dry_run=dry_run,
            allow_mutations=state.config.allow_mutations,
            skip_storage_box=skip_storage_box,
        )
    except (
        BackupConfigError,
        BackupLockError,
        BackupRunError,
        borg.BorgError,
        OSError,
        PermissionError,
        ValueError,
    ) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(result)
    else:
        mode = "DRY-RUN" if dry_run else "APPLY"
        typer.echo(f"Backup run ({mode}): ok={result.get('ok')} — {result.get('summary')}")
        for note in result.get("notes") or []:
            typer.echo(f"  note: {note}")
        for step in result.get("steps") or []:
            step_result = step.get("result") or {}
            typer.echo(
                f"  step[{step.get('name')}]: "
                f"ok={step_result.get('ok', step_result.get('status'))} "
                f"{step_result.get('summary', '')}"
            )
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("list")
def list_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
) -> None:
    """List archives in the configured repository (read-only)."""
    try:
        backup_config = load_backup_config(config)
        result = borg.list_archives(
            backup_config,
            target=state.target,
            timeout=state.config.command_timeout_seconds,
        )
    except (BackupConfigError, borg.BorgError, OSError, PermissionError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(result)
    else:
        typer.echo(f"Backup list: ok={result.get('ok')} — {result.get('summary')}")
        if result.get("stdout"):
            typer.echo(result["stdout"])
    if not result.get("ok"):
        raise typer.Exit(1)


@app.command("check")
def check_cmd(
    config: Annotated[
        Path | None,
        typer.Option(help="Backup YAML config path."),
    ] = None,
    full: Annotated[
        bool,
        typer.Option("--full", help="Run a full check instead of repository-only."),
    ] = False,
) -> None:
    """Run a repository check (read-only; lightweight by default)."""
    try:
        backup_config = load_backup_config(config)
        result = borg.check_repository(
            backup_config,
            target=state.target,
            timeout=state.config.command_timeout_seconds,
            full=full,
        )
    except (BackupConfigError, borg.BorgError, OSError, PermissionError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc

    if state.json_output:
        emit(result)
    else:
        typer.echo(f"Backup check: ok={result.get('ok')} — {result.get('summary')}")
        if result.get("stdout"):
            typer.echo(result["stdout"])
    if not result.get("ok"):
        raise typer.Exit(1)


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
