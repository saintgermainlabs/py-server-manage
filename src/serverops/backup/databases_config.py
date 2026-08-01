"""Load and validate the database backup allowlist."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from serverops.utils.secrets import REDACTED, redact_value


class DatabaseVaultRef(BaseModel):
    mount: str = "secret"
    path: str


class DatabaseCredentials(BaseModel):
    user: str | None = None
    password: str | None = None
    name: str | None = None


class DatabaseAllowlistEntry(BaseModel):
    id: str
    engine: Literal["postgresql", "mysql", "mariadb", "mongodb", "redis"]
    dump: Literal["native", "skip", "volume-only"] = "native"
    container_name: str | None = None
    coolify_uuid: str | None = None
    compose_project: str | None = None
    compose_service: str | None = None
    vault: DatabaseVaultRef | None = None
    credentials: DatabaseCredentials = Field(default_factory=DatabaseCredentials)

    def stable_identity(self) -> str:
        if self.coolify_uuid and not self.coolify_uuid.startswith("COOLIFY_UUID_"):
            return f"coolify:{self.coolify_uuid}"
        if self.compose_project and self.compose_service:
            return f"{self.compose_project}/{self.compose_service}"
        return self.container_name or self.id

    def has_placeholder_credentials(self) -> bool:
        for value in (
            self.credentials.user,
            self.credentials.password,
            self.credentials.name,
        ):
            if value and (
                value.startswith("VAULT_PLACEHOLDER_")
                or "{{" in value
                or value.startswith("COOLIFY_")
            ):
                return True
        return False


class DatabaseAllowlist(BaseModel):
    version: int = 1
    databases: list[DatabaseAllowlistEntry] = Field(default_factory=list)


class DatabaseAllowlistError(ValueError):
    """Raised when the database allowlist cannot be loaded."""


DEFAULT_DATABASES_PATH = Path("/etc/server-backup/databases.yaml")
EXAMPLE_DATABASES_PATH = Path(__file__).resolve().parents[3] / "config" / "databases.example.yaml"


def load_database_allowlist(path: Path | None = None) -> DatabaseAllowlist:
    """Load allowlist YAML. Missing file yields an empty allowlist."""
    candidate = path or DEFAULT_DATABASES_PATH
    if not candidate.is_file():
        return DatabaseAllowlist()
    loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise DatabaseAllowlistError(f"Database allowlist root must be a mapping: {candidate}")
    try:
        return DatabaseAllowlist.model_validate(loaded)
    except ValidationError as exc:
        raise DatabaseAllowlistError(str(exc)) from exc


def allowlist_for_display(allowlist: DatabaseAllowlist) -> dict[str, Any]:
    """Serialize allowlist with credential values redacted."""
    payload = allowlist.model_dump()
    for entry in payload.get("databases") or []:
        creds = entry.get("credentials") or {}
        for key in ("user", "password", "name"):
            if creds.get(key):
                creds[key] = REDACTED
    return redact_value(payload)


def reconcile_allowlist_with_discovery(
    allowlist: DatabaseAllowlist,
    discovered: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare allowlist entries to discovered probable databases (read-only)."""
    by_name = {
        str(item.get("container")): item
        for item in discovered
        if item.get("container")
    }
    matched: list[dict[str, Any]] = []
    missing_runtime: list[dict[str, Any]] = []
    for entry in allowlist.databases:
        runtime = by_name.get(entry.container_name or "")
        row = {
            "id": entry.id,
            "engine": entry.engine,
            "dump": entry.dump,
            "stable_identity": entry.stable_identity(),
            "container_name": entry.container_name,
            "runtime_found": runtime is not None,
            "runtime_engine": (runtime or {}).get("engine"),
            "credentials_ready": not entry.has_placeholder_credentials(),
        }
        if runtime is None:
            missing_runtime.append(row)
        else:
            matched.append(row)

    allowlisted_names = {e.container_name for e in allowlist.databases if e.container_name}
    unlisted = [
        {
            "container": item.get("container"),
            "engine": item.get("engine"),
            "proposed_backup_method": item.get("proposed_backup_method"),
        }
        for item in discovered
        if item.get("container") not in allowlisted_names
    ]
    return redact_value(
        {
            "matched": matched,
            "missing_runtime": missing_runtime,
            "discovered_not_allowlisted": unlisted,
            "summary": {
                "allowlisted": len(allowlist.databases),
                "matched": len(matched),
                "missing_runtime": len(missing_runtime),
                "discovered_not_allowlisted": len(unlisted),
            },
        }
    )
