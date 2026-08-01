"""Unit tests for Borg helpers and backup run/init workflows."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from serverops.backup.borg import (
    BorgError,
    create_archive,
    init_repository,
    list_archives,
    scrub_output,
)
from serverops.backup.credentials import load_credentials_env
from serverops.backup.models import BackupConfigModel, RepositoryConfig
from serverops.backup.preflight import run_preflight
from serverops.backup.run import (
    BackupLockError,
    BackupRunError,
    acquire_backup_lock,
    init_backup_repository,
    run_backup,
)
from serverops.cli import app
from serverops.models import CommandResult, Target

runner = CliRunner()


def _config(tmp_path: Path, *, url: str | None = None) -> BackupConfigModel:
    key = tmp_path / "server-backup-storagebox"
    key.write_text("fake-key\n", encoding="utf-8")
    creds = tmp_path / "credentials.env"
    creds.write_text("BORG_PASSPHRASE=fake-passphrase-value-xyz\n", encoding="utf-8")
    return BackupConfigModel(
        staging_directory=str(tmp_path / "staging"),
        restore_directory=str(tmp_path / "restore"),
        lock_file=str(tmp_path / "backup.lock"),
        command_timeout_seconds=30,
        repository=RepositoryConfig(
            url=url or "ssh://u12345-sub1@u12345.your-storagebox.de:23/./borg/server-primary",
            ssh_key=str(key),
        ),
        deploy={
            "install_root": str(tmp_path / "opt"),
            "config_dir": str(tmp_path / "etc-server-backup"),
            "credentials_file": str(creds),
            "borgmatic_config": str(tmp_path / "borgmatic.yaml"),
            "systemd_dir": str(tmp_path / "systemd"),
            "packages": ["borgbackup", "borgmatic"],
        },
        mandatory_sources=[str(tmp_path / "data")],
        host_configuration=[],
    )


def _ok_preflight(*_args, **_kwargs) -> dict:
    return {
        "ok": True,
        "error_count": 0,
        "warning_count": 0,
        "checks": [],
    }


def _fake_runner_factory(calls: list[list[str]], *, returncode: int = 0, stdout: str = "ok"):
    def _runner(
        argv: list[str],
        *,
        target: Target,
        timeout: int,
        allow_mutation: bool = False,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        calls.append(list(argv))
        if env and "fake-passphrase-value-xyz" in (env.get("BORG_PASSPHRASE") or ""):
            # Simulate accidental echo of passphrase in tool output.
            leaked = f"passphrase=fake-passphrase-value-xyz used for {argv[0]}"
            return CommandResult(
                argv=argv,
                returncode=returncode,
                stdout=stdout if returncode == 0 else "",
                stderr=leaked if returncode != 0 else "",
                duration_seconds=0.01,
            )
        return CommandResult(
            argv=argv,
            returncode=returncode,
            stdout=stdout,
            stderr="" if returncode == 0 else "failed",
            duration_seconds=0.01,
        )

    return _runner


def test_load_credentials_env(tmp_path: Path) -> None:
    path = tmp_path / "credentials.env"
    path.write_text(
        "# comment\nBORG_PASSPHRASE=fake-passphrase-value-xyz\nEMPTY=\n",
        encoding="utf-8",
    )
    loaded = load_credentials_env(path)
    assert loaded["BORG_PASSPHRASE"] == "fake-passphrase-value-xyz"
    assert loaded["EMPTY"] == ""


def test_scrub_output_removes_passphrase() -> None:
    cleaned = scrub_output("secret fake-passphrase-value-xyz here", ["fake-passphrase-value-xyz"])
    assert "fake-passphrase-value-xyz" not in cleaned


def test_init_dry_run_does_not_call_runner(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = init_repository(
        config,
        target=Target(),
        timeout=5,
        dry_run=True,
        runner=_fake_runner_factory(calls),
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert calls == []
    assert "borg" in result["argv"]


def test_init_apply_calls_borg_init(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = init_backup_repository(
        config,
        target=Target(),
        timeout=5,
        dry_run=False,
        allow_mutations=True,
        runner=_fake_runner_factory(calls),
    )
    assert result["ok"] is True
    assert calls == [["borg", "init", "--encryption=repokey-blake2", config.repository.url]]


def test_init_apply_requires_allow_mutations(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(BackupRunError, match="allow_mutations"):
        init_backup_repository(
            config,
            target=Target(),
            timeout=5,
            dry_run=False,
            allow_mutations=False,
        )


def test_placeholder_url_refused(tmp_path: Path) -> None:
    config = _config(tmp_path, url="ssh://STORAGE_USER@STORAGE_HOST:23/./borg/server-primary")
    with pytest.raises(BorgError, match="placeholders"):
        init_repository(config, target=Target(), timeout=5, dry_run=True)


def test_create_dry_run_does_not_call_runner(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = create_archive(
        config,
        target=Target(),
        timeout=5,
        dry_run=True,
        runner=_fake_runner_factory(calls),
    )
    assert result["dry_run"] is True
    assert calls == []
    assert "--dry-run" in result["argv"]


def test_run_dry_run_default_no_mutating_commands(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = run_backup(
        config,
        target=Target(),
        timeout=5,
        dry_run=True,
        allow_mutations=False,
        runner=_fake_runner_factory(calls),
        preflight_fn=_ok_preflight,
        skip_storage_box=True,
    )
    assert result["ok"] is True
    assert result["dry_run"] is True
    assert calls == []
    assert any("files-only" in note for note in result["notes"])


def test_run_apply_creates_and_checks(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = run_backup(
        config,
        target=Target(),
        timeout=5,
        dry_run=False,
        allow_mutations=True,
        runner=_fake_runner_factory(calls),
        preflight_fn=_ok_preflight,
        skip_storage_box=True,
    )
    assert result["ok"] is True, result
    assert calls[0][:2] == ["borgmatic", "create"]
    assert calls[1][:2] == ["borgmatic", "check"]
    assert Path(config.staging_directory).is_dir()


def test_run_apply_missing_apply_gate(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(BackupRunError, match="allow_mutations"):
        run_backup(
            config,
            target=Target(),
            timeout=5,
            dry_run=False,
            allow_mutations=False,
            preflight_fn=_ok_preflight,
        )


def test_run_command_failure(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = run_backup(
        config,
        target=Target(),
        timeout=5,
        dry_run=False,
        allow_mutations=True,
        runner=_fake_runner_factory(calls, returncode=1, stdout=""),
        preflight_fn=_ok_preflight,
        skip_storage_box=True,
    )
    assert result["ok"] is False
    assert "fake-passphrase-value-xyz" not in str(result)


def test_list_redacts_passphrase(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    config = _config(tmp_path)
    result = list_archives(
        config,
        target=Target(),
        timeout=5,
        runner=_fake_runner_factory(calls, returncode=1),
    )
    assert result["ok"] is False
    assert "fake-passphrase-value-xyz" not in str(result)


def test_lock_contention(tmp_path: Path) -> None:
    config = _config(tmp_path)
    held = acquire_backup_lock(config.lock_file)
    held.__enter__()
    try:
        with pytest.raises(BackupLockError), acquire_backup_lock(config.lock_file):
            pass
    finally:
        held.__exit__(None, None, None)


def test_preflight_require_credentials_errors(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "serverops.backup.preflight.shutil.which",
        lambda name: f"/usr/bin/{name}" if name in {"borg", "borgmatic", "docker"} else None,
    )
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
            {"returncode": 0, "stdout": "24.0", "stderr": ""},
        )(),
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
    config = BackupConfigModel(
        repository=RepositoryConfig(
            url="ssh://user@box.example:23/./borg/x",
            ssh_key=str(tmp_path / "missing-key"),
        ),
        deploy={"credentials_file": str(tmp_path / "missing-creds.env")},
        mandatory_sources=[str(tmp_path)],
        host_configuration=[],
    )
    result = run_preflight(
        config,
        target=Target(),
        timeout=5,
        require_credentials=True,
    )
    assert result["ok"] is False
    statuses = {item["name"]: item["status"] for item in result["checks"]}
    assert statuses["ssh_key"] == "error"
    assert statuses["credentials_file"] == "error"


def test_cli_run_dry_run_help_and_init_help() -> None:
    help_result = runner.invoke(app, ["backup", "--help"])
    assert help_result.exit_code == 0
    assert "init" in help_result.stdout
    assert "run" in help_result.stdout
