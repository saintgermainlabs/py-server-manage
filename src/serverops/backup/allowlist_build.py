"""Build a database allowlist from backup/Coolify inventories (no secrets)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from serverops.backup.databases_config import (
    DatabaseAllowlist,
    DatabaseAllowlistEntry,
    DatabaseCredentials,
    DatabaseVaultRef,
)
from serverops.backup.models import utc_now
from serverops.inventory.docker import classify_database_engine
from serverops.utils.secrets import redact_value

PLACEHOLDER_CREDS = DatabaseCredentials(
    user="VAULT_PLACEHOLDER_USERNAME",
    password="VAULT_PLACEHOLDER_PASSWORD",
    name="VAULT_PLACEHOLDER_DATABASE",
)

VAULT_MOUNT = "secret"
VAULT_PATH_PREFIX = "py-server-manage/backup/databases"


def _slug_id(*parts: str | None) -> str:
    raw = "-".join(p for p in parts if p)
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", raw).strip("-").lower()
    return cleaned[:80] or "database"


def _engine_from_blob(*parts: str | None) -> str | None:
    return classify_database_engine(" ".join(p or "" for p in parts), [])


def _dump_for_engine(engine: str | None) -> str:
    if engine == "redis":
        return "skip"
    if engine in {"postgresql", "mysql", "mariadb", "mongodb"}:
        return "native"
    return "skip"


def entry_from_backup_database(item: dict[str, Any]) -> DatabaseAllowlistEntry | None:
    engine = item.get("engine") or _engine_from_blob(str(item.get("image") or ""))
    if not engine:
        return None
    container = item.get("container")
    project = item.get("compose_project")
    service = item.get("compose_service")
    entry_id = _slug_id(project, service) if project and service else _slug_id(str(container or engine))
    return DatabaseAllowlistEntry(
        id=entry_id,
        engine=engine,  # type: ignore[arg-type]
        dump=_dump_for_engine(engine),  # type: ignore[arg-type]
        container_name=str(container) if container else None,
        compose_project=str(project) if project else None,
        compose_service=str(service) if service else None,
        vault=DatabaseVaultRef(mount=VAULT_MOUNT, path=f"{VAULT_PATH_PREFIX}/{entry_id}"),
        credentials=PLACEHOLDER_CREDS.model_copy() if engine != "redis" else DatabaseCredentials(),
    )


def entry_from_coolify_resource(
    item: dict[str, Any],
    *,
    source: str,
) -> DatabaseAllowlistEntry | None:
    name = str(item.get("name") or "")
    image = str(item.get("image") or "")
    db_type = str(item.get("database_type") or item.get("type") or "")
    # Prefer explicit Coolify database resources / images; avoid matching
    # app services merely named "…-with-postgres-…".
    engine: str | None = None
    if db_type:
        engine = _engine_from_blob(db_type, image)
    if engine is None and image:
        engine = _engine_from_blob(image)
    if engine is None and source == "databases":
        engine = _engine_from_blob(name, image, db_type)
    if engine is None and (
        "database" in name.lower()
        or re.match(
            r"^(postgres|postgresql|mysql|mariadb|mongo|mongodb|redis|valkey)([-_]|$)",
            name.lower(),
        )
    ):
        engine = _engine_from_blob(name)
    if not engine:
        return None
    uuid = item.get("uuid") or item.get("id")
    entry_id = _slug_id(str(uuid or name or engine))
    # Prefer human-ish id when name is descriptive
    if name and "database" in name.lower():
        entry_id = _slug_id(name.replace("database", "").strip("-_") or str(uuid))
    return DatabaseAllowlistEntry(
        id=entry_id,
        engine=engine,  # type: ignore[arg-type]
        dump=_dump_for_engine(engine),  # type: ignore[arg-type]
        container_name=name or None,
        coolify_uuid=str(uuid) if uuid else None,
        vault=DatabaseVaultRef(mount=VAULT_MOUNT, path=f"{VAULT_PATH_PREFIX}/{entry_id}"),
        credentials=PLACEHOLDER_CREDS.model_copy() if engine != "redis" else DatabaseCredentials(),
    )


def _merge_entries(entries: list[DatabaseAllowlistEntry]) -> list[DatabaseAllowlistEntry]:
    """Deduplicate by coolify_uuid, then container_name, then id."""
    by_key: dict[str, DatabaseAllowlistEntry] = {}
    for entry in entries:
        key = (
            f"uuid:{entry.coolify_uuid}"
            if entry.coolify_uuid
            else f"name:{entry.container_name}"
            if entry.container_name
            else f"id:{entry.id}"
        )
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = entry
            continue
        # Prefer entry with coolify_uuid and container_name filled
        merged = existing.model_copy(
            update={
                "coolify_uuid": existing.coolify_uuid or entry.coolify_uuid,
                "container_name": existing.container_name or entry.container_name,
                "compose_project": existing.compose_project or entry.compose_project,
                "compose_service": existing.compose_service or entry.compose_service,
            }
        )
        by_key[key] = merged
    # Ensure unique ids
    seen_ids: set[str] = set()
    out: list[DatabaseAllowlistEntry] = []
    for entry in by_key.values():
        entry_id = entry.id
        if entry_id in seen_ids:
            entry_id = _slug_id(entry_id, entry.coolify_uuid or entry.container_name)
            entry = entry.model_copy(
                update={
                    "id": entry_id,
                    "vault": DatabaseVaultRef(
                        mount=VAULT_MOUNT,
                        path=f"{VAULT_PATH_PREFIX}/{entry_id}",
                    ),
                }
            )
        seen_ids.add(entry.id)
        out.append(entry)
    return sorted(out, key=lambda e: e.id)


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Inventory file not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Inventory root must be a mapping: {path}")
    return loaded


def build_databases_allowlist(
    *,
    backup_inventory: dict[str, Any] | None = None,
    coolify_inventory: dict[str, Any] | None = None,
) -> tuple[DatabaseAllowlist, dict[str, Any]]:
    """Build allowlist with KV placeholders; return (allowlist, build_report)."""
    entries: list[DatabaseAllowlistEntry] = []
    sources_used: list[str] = []

    if backup_inventory:
        sources_used.append("backup-inventory")
        for item in backup_inventory.get("databases") or []:
            if isinstance(item, dict):
                entry = entry_from_backup_database(item)
                if entry:
                    entries.append(entry)

    if coolify_inventory:
        sources_used.append("coolify-inventory")
        for key in ("databases", "resources", "services", "applications"):
            for item in coolify_inventory.get(key) or []:
                if isinstance(item, dict):
                    entry = entry_from_coolify_resource(item, source=key)
                    if entry:
                        entries.append(entry)

    merged = _merge_entries(entries)
    allowlist = DatabaseAllowlist(version=1, databases=merged)
    report = redact_value(
        {
            "generated_at": utc_now(),
            "dry_run": True,
            "sources_used": sources_used,
            "summary": {
                "entries": len(merged),
                "native": sum(1 for e in merged if e.dump == "native"),
                "skip": sum(1 for e in merged if e.dump == "skip"),
            },
            "notes": [
                "Credentials are VAULT_PLACEHOLDER_* only — put real secrets in Vault KV "
                f"under {VAULT_MOUNT}/data/{VAULT_PATH_PREFIX}/<id>.",
                "Encrypt with: serverops inventory encrypt data/inventory/databases.yaml",
                "No database dumps were executed.",
            ],
        }
    )
    return allowlist, report


def allowlist_to_yaml(allowlist: DatabaseAllowlist) -> str:
    header = (
        "# Generated by serverops backup build-databases-allowlist.\n"
        "# Credentials are placeholders. Store real values in Vault KV, then either:\n"
        "#   - render via deploy/vault-agent/templates/databases.yaml.ctmpl, or\n"
        "#   - keep placeholders here and inject at dump time from KV.\n"
        "# Encrypt for git: serverops inventory encrypt <this-file>\n"
    )
    payload = allowlist.model_dump(exclude_none=True)
    body = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    return header + body
