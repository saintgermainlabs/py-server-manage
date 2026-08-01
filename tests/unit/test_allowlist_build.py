from __future__ import annotations

from pathlib import Path

import yaml

from serverops.backup.allowlist_build import (
    allowlist_to_yaml,
    build_databases_allowlist,
    entry_from_backup_database,
    entry_from_coolify_resource,
)


def test_entry_from_backup_database_postgres() -> None:
    entry = entry_from_backup_database(
        {
            "container": "coolify-db",
            "image": "postgres:15-alpine",
            "engine": "postgresql",
            "proposed_backup_method": "native-dump",
        }
    )
    assert entry is not None
    assert entry.engine == "postgresql"
    assert entry.dump == "native"
    assert entry.container_name == "coolify-db"
    assert entry.credentials.password == "VAULT_PLACEHOLDER_PASSWORD"
    assert entry.vault is not None
    assert entry.vault.path.endswith(entry.id)


def test_entry_from_coolify_redis_is_skip() -> None:
    entry = entry_from_coolify_resource(
        {
            "uuid": "r8xiurqdsxtx35xj99hler3d",
            "name": "redis-database-r8xiurqdsxtx35xj99hler3d",
            "image": "redis:7.2",
            "database_type": "standalone-redis",
        },
        source="databases",
    )
    assert entry is not None
    assert entry.engine == "redis"
    assert entry.dump == "skip"
    assert entry.coolify_uuid == "r8xiurqdsxtx35xj99hler3d"


def test_build_merges_backup_and_coolify(tmp_path: Path) -> None:
    backup = {
        "databases": [
            {
                "container": "coolify-db",
                "engine": "postgresql",
                "image": "postgres:15",
            }
        ]
    }
    coolify = {
        "resources": [
            {
                "uuid": "ngtyd6rj9n0n1gzqxap1f3gr",
                "name": "postgresql-database-ngtyd6rj9n0n1gzqxap1f3gr",
                "image": "postgres:18-alpine",
            }
        ],
        "databases": [
            {
                "uuid": "r8xiurqdsxtx35xj99hler3d",
                "name": "redis-database-r8xiurqdsxtx35xj99hler3d",
                "image": "redis:7.2",
                "database_type": "standalone-redis",
            }
        ],
    }
    allowlist, report = build_databases_allowlist(
        backup_inventory=backup,
        coolify_inventory=coolify,
    )
    assert report["summary"]["entries"] >= 3
    assert report["summary"]["native"] >= 2
    assert report["summary"]["skip"] >= 1
    text = allowlist_to_yaml(allowlist)
    loaded = yaml.safe_load(text)
    assert loaded["version"] == 1
    assert all(
        "VAULT_PLACEHOLDER_" in (db.get("credentials") or {}).get("password", "VAULT_PLACEHOLDER_")
        or db.get("engine") == "redis"
        for db in loaded["databases"]
    )
    out = tmp_path / "databases.yaml"
    out.write_text(text, encoding="utf-8")
    assert out.is_file()
