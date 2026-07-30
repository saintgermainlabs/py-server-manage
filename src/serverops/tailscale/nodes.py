#!/usr/bin/env python3
"""Parse a Tailscale API inventory export into a nodes-only view.

Drops users, keys, policy, DNS, and other non-node sections. Also strips the
per-device ``user`` field so the output is device-centric only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from serverops.paths import inventory_path

# Stable, ops-useful device fields. Intentionally excludes user identity and
# long-lived crypto key material that is not needed for a node inventory.
NODE_FIELDS: tuple[str, ...] = (
    "id",
    "nodeId",
    "hostname",
    "name",
    "addresses",
    "os",
    "distro",
    "clientVersion",
    "tags",
    "authorized",
    "connectedToControl",
    "lastSeen",
    "created",
    "expires",
    "keyExpiryDisabled",
    "advertisedRoutes",
    "enabledRoutes",
    "sshEnabled",
    "updateAvailable",
    "isExternal",
    "blocksIncomingConnections",
    "clientConnectivity",
)


def load_inventory(path: Path) -> dict[str, Any]:
    """Load a YAML or JSON API inventory export."""
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    elif suffix == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
        if data is None:
            data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"Inventory root must be a mapping, got {type(data).__name__}")
    return data


def _device_list(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    section = (inventory.get("inventory") or {}).get("devices")
    if isinstance(section, dict):
        devices = section.get("devices")
    elif isinstance(section, list):
        devices = section
    else:
        devices = None
    if not isinstance(devices, list):
        return []
    return [item for item in devices if isinstance(item, dict)]


def _detail_for_device(details: dict[str, Any], device: dict[str, Any]) -> dict[str, Any]:
    device_details = details.get("devices")
    if not isinstance(device_details, dict):
        return {}
    for key in ("id", "nodeId", "deviceId"):
        device_id = device.get(key)
        if device_id is None:
            continue
        entry = device_details.get(str(device_id))
        if isinstance(entry, dict):
            return entry
    return {}


def _pick_fields(source: dict[str, Any]) -> dict[str, Any]:
    return {field: source[field] for field in NODE_FIELDS if field in source}


def parse_node(device: dict[str, Any], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Normalize one device record into a nodes-only dict (no user fields)."""
    detail = detail or {}
    record = detail.get("record") if isinstance(detail.get("record"), dict) else {}
    routes = detail.get("routes") if isinstance(detail.get("routes"), dict) else {}

    merged: dict[str, Any] = {}
    merged.update(_pick_fields(record))
    merged.update(_pick_fields(device))
    if routes:
        if "advertisedRoutes" in routes:
            merged["advertisedRoutes"] = routes["advertisedRoutes"]
        if "enabledRoutes" in routes:
            merged["enabledRoutes"] = routes["enabledRoutes"]

    posture = detail.get("posture_attributes")
    if isinstance(posture, dict) and posture:
        merged["posture_attributes"] = posture

    # Never carry user identity into the nodes-only view.
    merged.pop("user", None)
    return merged


def parse_nodes(inventory: dict[str, Any]) -> dict[str, Any]:
    """Convert a full API inventory mapping into a nodes-only mapping.

    The result contains metadata about the source export plus a ``nodes`` list.
    Users, API keys, policy, DNS, and other non-device sections are omitted.
    """
    if not isinstance(inventory, dict):
        raise TypeError("inventory must be a dict")

    metadata = inventory.get("metadata") if isinstance(inventory.get("metadata"), dict) else {}
    details = inventory.get("details") if isinstance(inventory.get("details"), dict) else {}
    devices = _device_list(inventory)

    nodes = [parse_node(device, _detail_for_device(details, device)) for device in devices]
    nodes.sort(
        key=lambda item: (
            str(item.get("hostname") or item.get("name") or "").lower(),
            str((item.get("addresses") or [""])[0]),
        )
    )

    return {
        "schema_version": 1,
        "source": {
            "generated_at": metadata.get("generated_at"),
            "tailnet": metadata.get("tailnet"),
            "collector": metadata.get("collector"),
            "api_base": metadata.get("api_base"),
        },
        "node_count": len(nodes),
        "nodes": nodes,
    }


def parse_nodes_file(path: Path) -> dict[str, Any]:
    """Load an inventory file and return the nodes-only mapping."""
    return parse_nodes(load_inventory(path))


def write_nodes(data: dict[str, Any], output: Path, fmt: str = "yaml") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    output.write_text(
        yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        ),
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Parse a Tailscale API inventory into a nodes-only YAML/JSON file."
    )
    result.add_argument(
        "inventory",
        type=Path,
        nargs="?",
        default=inventory_path("tailscale-api-inventory.yaml"),
        help=(
            "Path to API inventory YAML/JSON "
            "(default: data/inventory/tailscale-api-inventory.yaml)."
        ),
    )
    result.add_argument(
        "-o",
        "--output",
        type=Path,
        default=inventory_path("tailscale-api-nodes.yaml"),
        help="Output path (default: data/inventory/tailscale-api-nodes.yaml).",
    )
    result.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        nodes = parse_nodes_file(args.inventory)
        write_nodes(nodes, args.output, args.format)
    except (OSError, ValueError, TypeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        print(f"Failed to parse nodes: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {nodes['node_count']} nodes to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
