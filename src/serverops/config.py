from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import Target


class CoolifyConfig(BaseModel):
    base_url: str | None = None
    verify_tls: bool = True


class FileConfig(BaseModel):
    default_target: str = "local"
    allow_mutations: bool = False
    command_timeout_seconds: int = 20
    coolify: CoolifyConfig = Field(default_factory=CoolifyConfig)
    targets: dict[str, Target] = Field(default_factory=lambda: {"local": Target()})


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    coolify_token: str | None = Field(default=None, alias="COOLIFY_TOKEN")

    def model_post_init(self, __context: object) -> None:
        if self.coolify_token:
            return
        # Accept the inventory script aliases without printing values.
        import os

        self.coolify_token = (
            os.environ.get("COOLIFY_API_KEY")
            or os.environ.get("COOLIFY_API_TOKEN")
            or self.coolify_token
        )


def load_config(path: Path | None) -> tuple[FileConfig, Secrets]:
    data: dict[str, Any] = {}
    if path and path.exists():
        data = yaml.safe_load(path.read_text()) or {}
    return FileConfig.model_validate(data), Secrets()
