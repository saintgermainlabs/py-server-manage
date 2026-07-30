"""Shared Pydantic models for ServerOps."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Status(StrEnum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    SKIPPED = "skipped"


class CheckResult(BaseModel):
    name: str
    status: Status
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)


class CommandResult(BaseModel):
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class Target(BaseModel):
    kind: str = "local"
    host: str | None = None
    user: str | None = None
    port: int = 22
