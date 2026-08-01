"""Backup package models and typed discovery results."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field


class PathProbe(BaseModel):
    path: str
    exists: bool = False
    is_dir: bool = False
    is_file: bool = False
    readable: bool = False
    size_bytes: int | None = None
    mode: str | None = None
    status: Literal["ok", "missing", "skipped", "error"] = "missing"
    summary: str = ""
    critical: bool = False
    relative: str | None = None


class RepositoryConfig(BaseModel):
    url: str = "ssh://STORAGE_USER@STORAGE_HOST:23/./borg/server-primary"
    ssh_key: str = "/root/.ssh/server-backup-storagebox"
    passphrase_environment_variable: str = "BORG_PASSPHRASE"

    def is_placeholder(self) -> bool:
        return "STORAGE_HOST" in self.url or "STORAGE_USER" in self.url

    def host_port(self) -> tuple[str | None, int]:
        parsed = urlparse(self.url)
        host = parsed.hostname
        port = parsed.port or 23
        return host, port


class DeployConfig(BaseModel):
    install_root: str = "/opt/py-server-manage"
    config_dir: str = "/etc/server-backup"
    credentials_file: str = "/etc/server-backup/credentials.env"
    databases_file: str = "/etc/server-backup/databases.yaml"
    borgmatic_config: str = "/etc/borgmatic/config.yaml"
    systemd_dir: str = "/etc/systemd/system"
    packages: list[str] = Field(default_factory=lambda: ["borgbackup", "borgmatic"])


class RetentionConfig(BaseModel):
    keep_within: str = "48H"
    keep_daily: int = 14
    keep_weekly: int = 8
    keep_monthly: int = 12
    keep_yearly: int = 3


class SchedulingConfig(BaseModel):
    nightly_calendar: str = "*-*-* 03:00:00"
    randomized_delay_seconds: int = 1800
    persistent: bool = True


class BackupConfigModel(BaseModel):
    """Validated backup configuration for discovery, generate-config, and install."""

    version: int = 1
    server_name: str = "hetzner-primary"
    staging_directory: str = "/var/lib/server-backup/staging"
    restore_directory: str = "/var/lib/server-backup/restore"
    lock_file: str = "/run/lock/server-backup.lock"
    mandatory_sources: list[str] = Field(
        default_factory=lambda: [
            "/data",
            "/srv/projects",
            "/opt",
            "/home/dom/projects",
        ]
    )
    host_configuration: list[str] = Field(
        default_factory=lambda: [
            "/etc",
            "/usr/local/bin",
            "/usr/local/sbin",
            "/root/.ssh",
        ]
    )
    exclusions: list[str] = Field(
        default_factory=lambda: [
            "/proc",
            "/sys",
            "/dev",
            "/run",
            "/tmp",
            "/var/tmp",
            "/var/cache",
            "/var/lib/docker/overlay2",
            "/var/lib/docker/image",
        ]
    )
    repository: RepositoryConfig = Field(default_factory=RepositoryConfig)
    deploy: DeployConfig = Field(default_factory=DeployConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    scheduling: SchedulingConfig = Field(default_factory=SchedulingConfig)
    additional_sources: list[str] = Field(default_factory=list)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def empty_manifest(**extra: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": utc_now(),
        **extra,
    }
