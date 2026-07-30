"""Read-only backup discovery orchestration."""

from __future__ import annotations

from typing import Any

from serverops.backup.config import load_backup_config
from serverops.backup.models import BackupConfigModel, utc_now
from serverops.inventory import coolify as coolify_inventory
from serverops.inventory import docker as docker_inventory
from serverops.inventory import system as system_inventory
from serverops.models import Target
from serverops.utils.filesystem import path_probe
from serverops.utils.secrets import redact_value


def discover(
    *,
    target: Target,
    timeout: int,
    config: BackupConfigModel | None = None,
) -> dict[str, Any]:
    """Discover backup-relevant resources without mutating system state."""
    cfg = config or load_backup_config()
    mandatory = [path_probe(path) for path in cfg.mandatory_sources]
    host_configuration = [path_probe(path) for path in cfg.host_configuration]
    docker = docker_inventory.discover_docker(target, timeout)
    system = system_inventory.discover_system(target, timeout)
    coolify = coolify_inventory.discover_coolify()

    databases = [
        {
            "container": item.get("name"),
            "image": item.get("image"),
            "engine": item.get("probable_database"),
            "compose_project": item.get("compose_project"),
            "compose_service": item.get("compose_service"),
            "proposed_backup_method": (
                "native-dump"
                if item.get("probable_database") not in {None, "redis"}
                else "review-redis-durability"
                if item.get("probable_database") == "redis"
                else None
            ),
        }
        for item in docker.get("containers") or []
        if item.get("probable_database")
    ]

    payload = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "collector": "serverops.backup.discover",
        "server_name": cfg.server_name,
        "target": {"kind": target.kind, "host": target.host},
        "summary": {
            "mandatory_paths_ok": sum(1 for item in mandatory if item.get("status") == "ok"),
            "mandatory_paths_total": len(mandatory),
            "containers": len(docker.get("containers") or []),
            "volumes": len(docker.get("volumes") or []),
            "probable_databases": len(databases),
            "docker_available": bool(docker.get("available")),
        },
        "mandatory_sources": mandatory,
        "host_configuration": host_configuration,
        "exclusions": cfg.exclusions,
        "coolify": coolify,
        "docker": docker,
        "databases": databases,
        "system": system,
        "review_notes": _review_notes(mandatory, coolify, databases, docker),
    }
    return redact_value(payload)


def _review_notes(
    mandatory: list[dict[str, Any]],
    coolify: dict[str, Any],
    databases: list[dict[str, Any]],
    docker: dict[str, Any],
) -> list[str]:
    notes: list[str] = []
    for item in mandatory:
        if item.get("status") != "ok":
            notes.append(f"Mandatory path not ready: {item.get('path')} ({item.get('status')})")
    for item in coolify.get("critical_items") or []:
        if item.get("status") != "ok":
            notes.append(
                f"Coolify recovery item not ready: {item.get('path')} ({item.get('status')})"
            )
    if not docker.get("available"):
        notes.append("Docker CLI unavailable; container/volume discovery was skipped.")
    for db in databases:
        if db.get("engine") == "redis":
            notes.append(
                f"Redis container {db.get('container')} needs durability review before backup."
            )
    if not databases:
        notes.append("No probable database containers detected; confirm manually on the server.")
    return notes
