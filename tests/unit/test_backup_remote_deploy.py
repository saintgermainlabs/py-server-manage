from __future__ import annotations

from pathlib import Path

import yaml

from serverops.backup.config import load_backup_config
from serverops.backup.generate import generate_configs
from serverops.backup.install import build_install_plan, install_backup_system
from serverops.backup.models import BackupConfigModel, RepositoryConfig
from serverops.backup.preflight import run_preflight
from serverops.models import Target


def test_generate_configs_writes_expected_files(tmp_path: Path) -> None:
    config = load_backup_config()
    written = generate_configs(config, output_dir=tmp_path)
    assert set(written) >= {
        "backup_yaml",
        "borgmatic",
        "credentials_example",
        "service",
        "timer",
        "check_service",
        "check_timer",
        "borgmatic_dropin",
    }
    for path in written.values():
        assert path.is_file()
        assert path.stat().st_size > 0

    text = written["borgmatic"].read_text(encoding="utf-8")
    borgmatic = yaml.safe_load(
        "\n".join(line for line in text.splitlines() if not line.startswith("#"))
    )
    assert "/data" in borgmatic["source_directories"]
    assert "STORAGE_HOST" in borgmatic["repositories"][0]["path"]
    assert "printenv BORG_PASSPHRASE" in text or "cat /etc/server-backup/borg-passphrase" in text
    assert "UMask=0077" in written["service"].read_text(encoding="utf-8")
    dropin = written["borgmatic_dropin"].read_text(encoding="utf-8")
    assert "EnvironmentFile=-/etc/server-backup/credentials.env" in dropin
    creds = written["credentials_example"].read_text(encoding="utf-8")
    assert "BORG_PASSPHRASE=" in creds
    assert "super-secret" not in creds


def test_install_dry_run_does_not_write_live_paths(tmp_path: Path) -> None:
    config = BackupConfigModel(
        staging_directory=str(tmp_path / "staging"),
        restore_directory=str(tmp_path / "restore"),
        deploy={
            "install_root": str(tmp_path / "opt"),
            "config_dir": str(tmp_path / "etc-server-backup"),
            "credentials_file": str(tmp_path / "etc-server-backup" / "credentials.env"),
            "borgmatic_config": str(tmp_path / "etc-borgmatic" / "config.yaml"),
            "systemd_dir": str(tmp_path / "systemd"),
            "packages": ["borgbackup", "borgmatic"],
        },
    )
    generated = tmp_path / "generated"
    result = install_backup_system(config, dry_run=True, force=False, generated_dir=generated)
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert (generated / "borgmatic.yaml").is_file()
    assert not Path(config.deploy.config_dir).exists()
    assert not Path(config.deploy.systemd_dir).exists()
    plan = build_install_plan(config, generated_dir=generated, force=False)
    assert any(item["kind"] == "copy" for item in plan)
    assert any(item["kind"] == "mkdir" for item in plan)


def test_install_apply_to_temp_tree(tmp_path: Path) -> None:
    config = BackupConfigModel(
        staging_directory=str(tmp_path / "staging"),
        restore_directory=str(tmp_path / "restore"),
        deploy={
            "install_root": str(tmp_path / "opt"),
            "config_dir": str(tmp_path / "etc-server-backup"),
            "credentials_file": str(tmp_path / "etc-server-backup" / "credentials.env"),
            "borgmatic_config": str(tmp_path / "etc-borgmatic" / "config.yaml"),
            "systemd_dir": str(tmp_path / "systemd"),
            "packages": ["borgbackup"],
        },
    )
    generated = tmp_path / "generated"
    result = install_backup_system(config, dry_run=False, force=False, generated_dir=generated)
    assert result["ok"] is True, result.get("errors")
    assert (Path(config.deploy.config_dir) / "backup.yaml").is_file()
    assert Path(config.deploy.borgmatic_config).is_file()
    assert Path(config.deploy.credentials_file).is_file()
    assert (Path(config.deploy.systemd_dir) / "server-backup.timer").is_file()
    assert (
        Path(config.deploy.systemd_dir) / "borgmatic.service.d" / "credentials.conf"
    ).is_file()

    again = install_backup_system(config, dry_run=False, force=False, generated_dir=generated)
    assert again["ok"] is True
    assert again["skipped"]


def test_preflight_placeholder_skips_storage_box(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "serverops.backup.preflight.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"borg", "borgmatic", "docker"} else None,
    )
    monkeypatch.setattr(
        "serverops.backup.preflight.path_probe",
        lambda path: {
            "path": str(path),
            "exists": False,
            "status": "missing",
            "summary": "missing",
        },
    )
    monkeypatch.setattr(
        "serverops.backup.preflight.run_read_only",
        lambda *args, **kwargs: type(
            "R",
            (),
            {"returncode": 0, "stdout": "24.0", "stderr": ""},
        )(),
    )
    config = BackupConfigModel(
        repository=RepositoryConfig(ssh_key=str(tmp_path / "missing-key")),
        deploy={"credentials_file": str(tmp_path / "missing-creds.env")},
    )
    result = run_preflight(config, target=Target(), timeout=5)
    assert result["repository_placeholder"] is True
    statuses = {item["name"]: item["status"] for item in result["checks"]}
    assert statuses["storage_box_tcp"] == "skipped"
    assert statuses["tool:borg"] == "ok"
    assert result["ok"] is True


def test_preflight_errors_when_borg_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("serverops.backup.preflight.shutil.which", lambda name: None)
    monkeypatch.setattr(
        "serverops.backup.preflight.path_probe",
        lambda path: {
            "path": str(path),
            "exists": True,
            "status": "ok",
            "summary": "ok",
        },
    )
    monkeypatch.setattr(
        "serverops.backup.preflight.run_read_only",
        lambda *args, **kwargs: type(
            "R",
            (),
            {"returncode": 1, "stdout": "", "stderr": "no docker"},
        )(),
    )
    config = BackupConfigModel(
        repository=RepositoryConfig(
            url="ssh://user@box.example:23/./borg/server-primary",
            ssh_key=str(tmp_path / "key"),
        ),
        deploy={"credentials_file": str(tmp_path / "creds.env")},
    )
    monkeypatch.setattr(
        "serverops.backup.preflight._storage_box_check",
        lambda config, timeout: {
            "name": "storage_box_tcp",
            "status": "ok",
            "summary": "ok",
            "evidence": {},
        },
    )
    result = run_preflight(config, target=Target(), timeout=5)
    assert result["ok"] is False
    assert result["error_count"] >= 1


def test_load_backup_config_includes_deploy() -> None:
    config = load_backup_config()
    assert config.deploy.install_root == "/opt/py-server-manage"
    assert config.deploy.config_dir == "/etc/server-backup"
    assert config.repository.ssh_key.endswith("server-backup-storagebox")
