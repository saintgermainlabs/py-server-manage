"""Shared CLI runtime state for module commands."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console

from serverops.config import FileConfig, Secrets
from serverops.models import Target

console = Console()


class AppState:
    config: FileConfig
    secrets: Secrets
    json_output: bool = False
    target: Target


state = AppState()


def emit(value: Any) -> None:
    if state.json_output:
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        console.print_json(json.dumps(value))
    else:
        console.print(value)
