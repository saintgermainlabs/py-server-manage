from typer.testing import CliRunner

from serverops.cli import app

runner = CliRunner()


def test_root_help_includes_backup() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "backup" in result.stdout


def test_backup_help() -> None:
    result = runner.invoke(app, ["backup", "--help"])
    assert result.exit_code == 0
    assert "discover" in result.stdout
