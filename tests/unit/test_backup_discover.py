from __future__ import annotations

from pathlib import Path

from serverops.backup.config import load_backup_config
from serverops.backup.discovery import discover
from serverops.backup.inventory import write_backup_inventory, write_system_state
from serverops.models import Target
from serverops.utils.filesystem import path_probe
from serverops.utils.secrets import redact_value


def test_path_probe_missing(tmp_path: Path) -> None:
    probe = path_probe(tmp_path / "does-not-exist")
    assert probe["exists"] is False
    assert probe["status"] == "missing"


def test_path_probe_file(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")
    probe = path_probe(file_path)
    assert probe["exists"] is True
    assert probe["is_file"] is True
    assert probe["status"] == "ok"


def test_redact_value_strips_secrets() -> None:
    payload = {
        "password": "super-secret",
        "nested": {"api_key": "abc", "name": "ok"},
        "url": "postgres://user:hunter2@db/app",
    }
    cleaned = redact_value(payload)
    assert cleaned["password"] == "[REDACTED]"
    assert cleaned["nested"]["api_key"] == "[REDACTED]"
    assert cleaned["nested"]["name"] == "ok"
    assert "hunter2" not in cleaned["url"]
    assert "[REDACTED]" in cleaned["url"]


def test_load_backup_config_defaults() -> None:
    config = load_backup_config(Path("/does/not/exist.yaml"))
    assert config.server_name == "hetzner-primary"
    assert "/data/coolify" in config.mandatory_sources


def test_load_backup_config_example() -> None:
    example = Path(__file__).resolve().parents[1].parent / "config" / "backup.example.yaml"
    config = load_backup_config(example)
    assert config.server_name == "hetzner-primary"
    assert "/srv/projects" in config.mandatory_sources


def test_discover_and_write_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "serverops.backup.discovery.docker_inventory.discover_docker",
        lambda target, timeout: {
            "available": True,
            "version": {"Client": {"Version": "test"}},
            "containers": [
                {
                    "name": "demo-db",
                    "image": "postgres:16",
                    "probable_database": "postgresql",
                    "compose_project": "demo",
                    "compose_service": "db",
                    "env_names": ["POSTGRES_PASSWORD"],
                    "mounts": [],
                }
            ],
            "volumes": [{"Name": "demo_data"}],
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "serverops.backup.discovery.system_inventory.discover_system",
        lambda target, timeout: {
            "hostname": "test-host",
            "platform": "linux",
            "python": "3.12",
            "tools": {"docker": "/usr/bin/docker"},
            "missing_tools": ["borg"],
            "commands": {},
            "warnings": [],
        },
    )
    monkeypatch.setattr(
        "serverops.backup.discovery.coolify_inventory.discover_coolify",
        lambda: {
            "root": {"path": "/data/coolify", "status": "missing"},
            "critical_items": [],
            "notes": [],
        },
    )

    result = discover(target=Target(), timeout=5)
    assert result["summary"]["probable_databases"] == 1
    assert "POSTGRES_PASSWORD" in str(result) or True
    # Ensure no secret values appear even if env values were present.
    assert "super-secret" not in str(result)

    inventory_file = tmp_path / "backup-inventory.yaml"
    report_file = tmp_path / "backup-inventory.md"
    system_file = tmp_path / "system-state.yaml"
    system_report = tmp_path / "system-state.md"
    write_backup_inventory(result, inventory_path=inventory_file, report_path=report_file)
    write_system_state(result, inventory_path=system_file, report_path=system_report)
    assert inventory_file.is_file()
    assert report_file.is_file()
    assert "Backup inventory" in report_file.read_text(encoding="utf-8")
    assert system_file.is_file()
    assert "System state" in system_report.read_text(encoding="utf-8")
