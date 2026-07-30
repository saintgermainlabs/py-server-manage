from pathlib import Path

from serverops.config import load_config


def test_defaults_without_file() -> None:
    config, _ = load_config(Path("/does/not/exist"))
    assert config.default_target == "local"
    assert config.allow_mutations is False
