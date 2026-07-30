"""Serialize discovery results to YAML and Markdown reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from serverops.paths import data_path
from serverops.utils.filesystem import ensure_parent
from serverops.utils.secrets import redact_value


def write_backup_inventory(
    discovery: dict[str, Any],
    *,
    inventory_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Path]:
    """Write machine inventory YAML and a human Markdown summary."""
    inventory_file = inventory_path or data_path("inventory", "backup-inventory.yaml")
    report_file = report_path or data_path("reports", "backup-inventory.md")
    clean = redact_value(discovery)
    _write_yaml(inventory_file, clean)
    ensure_parent(report_file)
    report_file.write_text(_markdown_inventory(clean), encoding="utf-8")
    return {"inventory": inventory_file, "report": report_file}


def write_system_state(
    discovery: dict[str, Any],
    *,
    inventory_path: Path | None = None,
    report_path: Path | None = None,
) -> dict[str, Path]:
    """Write system-state YAML/Markdown derived from discovery."""
    system = {
        "schema_version": 1,
        "generated_at": discovery.get("generated_at"),
        "server_name": discovery.get("server_name"),
        "system": discovery.get("system") or {},
        "docker_available": (discovery.get("docker") or {}).get("available"),
        "tooling": (discovery.get("system") or {}).get("tools") or {},
        "missing_tools": (discovery.get("system") or {}).get("missing_tools") or [],
    }
    inventory_file = inventory_path or data_path("inventory", "system-state.yaml")
    report_file = report_path or data_path("reports", "system-state.md")
    clean = redact_value(system)
    _write_yaml(inventory_file, clean)
    ensure_parent(report_file)
    report_file.write_text(_markdown_system(clean), encoding="utf-8")
    return {"inventory": inventory_file, "report": report_file}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _markdown_inventory(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    lines = [
        "# Backup inventory",
        "",
        f"Generated: `{data.get('generated_at')}`",
        f"Server: `{data.get('server_name')}`",
        "",
        "## Summary",
        "",
        f"- Mandatory paths ready: {summary.get('mandatory_paths_ok')}/"
        f"{summary.get('mandatory_paths_total')}",
        f"- Containers: {summary.get('containers')}",
        f"- Volumes: {summary.get('volumes')}",
        f"- Probable databases: {summary.get('probable_databases')}",
        f"- Docker available: {summary.get('docker_available')}",
        "",
        "## Mandatory sources",
        "",
    ]
    for item in data.get("mandatory_sources") or []:
        lines.append(f"- `{item.get('path')}` — **{item.get('status')}** — {item.get('summary')}")
    lines.extend(["", "## Coolify critical items", ""])
    for item in (data.get("coolify") or {}).get("critical_items") or []:
        lines.append(f"- `{item.get('path')}` — **{item.get('status')}** — {item.get('summary')}")
    lines.extend(["", "## Probable databases", ""])
    databases = data.get("databases") or []
    if not databases:
        lines.append("- None detected")
    for item in databases:
        lines.append(
            f"- `{item.get('container')}` ({item.get('engine')}) via "
            f"`{item.get('proposed_backup_method')}`"
        )
    notes = data.get("review_notes") or []
    if notes:
        lines.extend(["", "## Review notes", ""])
        lines.extend(f"- {note}" for note in notes)
    lines.append("")
    return "\n".join(lines)


def _markdown_system(data: dict[str, Any]) -> str:
    system = data.get("system") or {}
    lines = [
        "# System state",
        "",
        f"Generated: `{data.get('generated_at')}`",
        f"Hostname: `{system.get('hostname')}`",
        f"Platform: `{system.get('platform')}`",
        "",
        "## Backup-related tools",
        "",
    ]
    tools = data.get("tooling") or {}
    if tools:
        lines.extend(f"- `{name}`: `{path}`" for name, path in sorted(tools.items()))
    else:
        lines.append("- None detected on PATH")
    missing = data.get("missing_tools") or []
    if missing:
        lines.extend(["", "## Missing tools", ""])
        lines.extend(f"- `{name}`" for name in missing)
    disk = ((system.get("commands") or {}).get("disk") or {}).get("stdout")
    if disk:
        lines.extend(["", "## Disk", "", "```", disk, "```"])
    lines.append("")
    return "\n".join(lines)
