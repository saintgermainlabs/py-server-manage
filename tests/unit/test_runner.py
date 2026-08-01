import pytest

from serverops.models import Target
from serverops.runner import is_read_only, run_command


def test_read_only_allowlist() -> None:
    assert is_read_only(["docker", "ps"])
    assert is_read_only(["journalctl", "-u", "docker"])
    assert is_read_only(["borgmatic", "list", "--config", "/etc/borgmatic/config.yaml"])
    assert is_read_only(["borgmatic", "check", "--config", "/etc/borgmatic/config.yaml"])
    assert not is_read_only(["docker", "restart", "app"])
    assert not is_read_only(["borgmatic", "create", "--config", "/etc/borgmatic/config.yaml"])


def test_mutating_command_is_rejected() -> None:
    with pytest.raises(PermissionError):
        run_command(["docker", "restart", "app"], target=Target(), timeout=1)
