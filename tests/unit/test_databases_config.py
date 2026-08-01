from __future__ import annotations

from pathlib import Path

from serverops.backup.databases_config import (
    load_database_allowlist,
    reconcile_allowlist_with_discovery,
)


def test_load_database_allowlist_example() -> None:
    example = Path(__file__).resolve().parents[1].parent / "config" / "databases.example.yaml"
    allowlist = load_database_allowlist(example)
    assert allowlist.version == 1
    assert len(allowlist.databases) >= 6
    coolify = next(item for item in allowlist.databases if item.id == "coolify-db")
    assert coolify.engine == "postgresql"
    assert coolify.dump == "native"
    assert coolify.vault is not None
    assert coolify.vault.path.endswith("coolify-db")
    assert coolify.has_placeholder_credentials() is True


def test_reconcile_allowlist_with_discovery() -> None:
    example = Path(__file__).resolve().parents[1].parent / "config" / "databases.example.yaml"
    allowlist = load_database_allowlist(example)
    discovered = [
        {
            "container": "coolify-db",
            "engine": "postgresql",
            "proposed_backup_method": "native-dump",
        },
        {
            "container": "mystery-pg",
            "engine": "postgresql",
            "proposed_backup_method": "native-dump",
        },
    ]
    result = reconcile_allowlist_with_discovery(allowlist, discovered)
    assert result["summary"]["matched"] == 1
    assert result["summary"]["discovered_not_allowlisted"] == 1
    assert result["matched"][0]["id"] == "coolify-db"
    assert result["discovered_not_allowlisted"][0]["container"] == "mystery-pg"


def test_missing_allowlist_is_empty() -> None:
    allowlist = load_database_allowlist(Path("/does/not/exist-databases.yaml"))
    assert allowlist.databases == []
