"""Backup configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from serverops.backup.models import BackupConfigModel
from serverops.paths import REPO_ROOT


class BackupConfigError(ValueError):
    """Raised when backup configuration is invalid."""


def default_config_path() -> Path:
    return REPO_ROOT / "config" / "backup.example.yaml"


def load_backup_config(path: Path | None = None) -> BackupConfigModel:
    """Load backup YAML; missing file yields safe defaults."""
    candidate = path or default_config_path()
    data: dict[str, Any] = {}
    if candidate.is_file():
        loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise BackupConfigError(f"Backup config root must be a mapping: {candidate}")
        data = _flatten_example(loaded)
    try:
        return BackupConfigModel.model_validate(data)
    except ValidationError as exc:
        raise BackupConfigError(str(exc)) from exc


def _flatten_example(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept both flat and nested example shapes from backup.example.yaml."""
    if "server" in raw or "sources" in raw or "repository" in raw or "deploy" in raw:
        server = raw.get("server") if isinstance(raw.get("server"), dict) else {}
        sources = raw.get("sources") if isinstance(raw.get("sources"), dict) else {}
        repository = raw.get("repository") if isinstance(raw.get("repository"), dict) else {}
        deploy = raw.get("deploy") if isinstance(raw.get("deploy"), dict) else {}
        retention = raw.get("retention") if isinstance(raw.get("retention"), dict) else {}
        scheduling = raw.get("scheduling") if isinstance(raw.get("scheduling"), dict) else {}
        defaults = BackupConfigModel()
        return {
            "version": raw.get("version", 1),
            "server_name": server.get("name", defaults.server_name),
            "staging_directory": server.get("staging_directory", defaults.staging_directory),
            "restore_directory": server.get("restore_directory", defaults.restore_directory),
            "lock_file": server.get("lock_file", defaults.lock_file),
            "mandatory_sources": sources.get("mandatory") or defaults.mandatory_sources,
            "host_configuration": sources.get("host_configuration") or defaults.host_configuration,
            "additional_sources": sources.get("additional") or [],
            "exclusions": raw.get("exclusions") or defaults.exclusions,
            "repository": repository or defaults.repository.model_dump(),
            "deploy": deploy or defaults.deploy.model_dump(),
            "retention": retention or defaults.retention.model_dump(),
            "scheduling": scheduling or defaults.scheduling.model_dump(),
        }
    return raw
