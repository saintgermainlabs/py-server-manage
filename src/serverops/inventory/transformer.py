#!/usr/bin/env python3
"""Transform Tailscale and Coolify inventories for dashboards and templates.

Dashboard examples:
    uv run python -m serverops.inventory_transformer dashboard
    uv run python -m serverops.inventory_transformer dashboard \\
        --tailscale data/inventory/tailscale-inventory.yaml \\
        --coolify data/inventory/coolify-inventory.yaml \\
        --output-dir data/transformed/dashboard

Template example:
    uv run python -m serverops.inventory_transformer template \\
        --coolify data/inventory/coolify-inventory.yaml \\
        --output-dir data/transformed/templates

The script is local and read-only with respect to Tailscale and Coolify. It
only reads inventory files and writes transformed files beneath --output-dir.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from serverops.paths import data_path, inventory_path

try:
    import yaml
except ImportError:
    print(
        "PyYAML is required. Run with:\n"
        "  uv run --with pyyaml python -m serverops.inventory_transformer ...",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


REDACTED = "[REDACTED]"
COMPOSE_FIELDS = (
    "docker_compose_raw",
    "docker_compose",
    "compose_raw",
    "compose",
)
RESOURCE_KINDS = ("services", "applications", "databases")


class TransformError(RuntimeError):
    """Raised for invalid input or unsafe output paths."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Transform infrastructure inventories for portal dashboards or Compose templates."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    dashboard = subparsers.add_parser(
        "dashboard", help="Create dashboard-oriented Tailnet and Coolify datasets."
    )
    dashboard.add_argument(
        "--tailscale",
        type=Path,
        default=inventory_path("tailscale-inventory.yaml"),
        help="Tailscale inventory YAML/JSON (default: data/inventory/tailscale-inventory.yaml).",
    )
    dashboard.add_argument(
        "--coolify",
        type=Path,
        default=inventory_path("coolify-inventory.yaml"),
        help="Coolify inventory YAML/JSON (default: data/inventory/coolify-inventory.yaml).",
    )
    dashboard.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=data_path("transformed", "dashboard"),
        help="Destination directory (default: data/transformed/dashboard).",
    )
    dashboard.add_argument(
        "--format",
        choices=("yaml", "json", "both"),
        default="yaml",
        help="Dashboard output format (default: yaml).",
    )

    template = subparsers.add_parser(
        "template",
        aliases=["transform"],
        help="Organize Coolify Compose definitions into a template workspace.",
    )
    template.add_argument(
        "--coolify",
        type=Path,
        default=inventory_path("coolify-inventory.yaml"),
        help="Coolify inventory YAML/JSON (default: data/inventory/coolify-inventory.yaml).",
    )
    template.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=data_path("transformed", "templates"),
        help="Destination directory (default: data/transformed/templates).",
    )
    template.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing generated source/template files.",
    )
    return parser.parse_args()


def load_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise TransformError(f"Inventory file does not exist: {path}")
    try:
        text = path.read_text(encoding="utf-8")
        value = json.loads(text) if path.suffix.lower() == ".json" else yaml.safe_load(text)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise TransformError(f"Could not parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransformError(f"Expected a mapping at the top level of {path}")
    return value


def write_document(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        content = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    else:
        content = yaml.safe_dump(
            value,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    path.write_text(content, encoding="utf-8")


def string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def first(*values: Any) -> Any:
    return next((value for value in values if value not in (None, "", [], {})), None)


def list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def list_of_strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def nested_get(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def slugify(value: Any, fallback: str = "unnamed") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or fallback


def unique_strings(values: Iterable[Any]) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value))


def extract_command_data(value: Any) -> Any:
    """Unwrap the command_result() shape used by tailscale_inventory.py."""
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def tailscale_nodes(inventory: dict[str, Any]) -> list[dict[str, Any]]:
    explicit = inventory.get("nodes")
    if isinstance(explicit, list):
        return list_of_dicts(explicit)

    status = extract_command_data(inventory.get("status"))
    if not isinstance(status, dict):
        status = extract_command_data(nested_get(inventory, "commands", "status"))
    if not isinstance(status, dict):
        return []

    nodes: list[dict[str, Any]] = []
    self_node = status.get("Self")
    if isinstance(self_node, dict):
        nodes.append({**self_node, "_is_self": True})
    peers = status.get("Peer")
    if isinstance(peers, dict):
        nodes.extend(item for item in peers.values() if isinstance(item, dict))
    elif isinstance(peers, list):
        nodes.extend(list_of_dicts(peers))
    return nodes


def normalize_tailscale_node(node: dict[str, Any]) -> dict[str, Any]:
    # CLI inventory stores the raw peer/self record under ``status``.
    nested = node.get("status")
    record = nested if isinstance(nested, dict) else {}

    whois = extract_command_data(node.get("whois"))
    ping = node.get("ping") if isinstance(node.get("ping"), dict) else {}
    addresses = unique_strings(
        [
            *list_of_strings(node.get("TailscaleIPs")),
            *list_of_strings(node.get("tailscale_ips")),
            *list_of_strings(node.get("addresses")),
            *list_of_strings(record.get("TailscaleIPs")),
            node.get("primary_tailscale_ip"),
        ]
    )
    ipv4 = next((address for address in addresses if ":" not in address), None)
    ipv6 = next((address for address in addresses if ":" in address), None)
    dns_name = first(node.get("DNSName"), node.get("dns_name"), record.get("DNSName"))
    name = first(
        node.get("name"),
        node.get("HostName"),
        node.get("hostname"),
        record.get("HostName"),
        dns_name.rstrip(".") if isinstance(dns_name, str) else None,
    )
    online = first(node.get("Online"), node.get("online"), record.get("Online"))
    status_value = node.get("status") if isinstance(node.get("status"), str) else None
    status = first(status_value, "online" if online is True else None)
    if status is None and online is False:
        status = "offline"

    tags = unique_strings(
        [
            *list_of_strings(node.get("Tags")),
            *list_of_strings(node.get("tags")),
            *list_of_strings(record.get("Tags")),
            *list_of_strings(nested_get(whois, "Node", "Tags")),
        ]
    )
    user_profile = nested_get(whois, "UserProfile")
    return {
        "id": first(
            node.get("StableID"),
            node.get("stable_id"),
            node.get("ID"),
            node.get("id"),
            node.get("nodeId"),
            record.get("ID"),
            ipv4,
            name,
        ),
        "name": name,
        "hostname": first(node.get("HostName"), node.get("hostname"), record.get("HostName")),
        "dns_name": dns_name,
        "addresses": addresses,
        "ipv4": ipv4,
        "ipv6": ipv6,
        "online": online,
        "status": status or "unknown",
        "is_self": bool(first(node.get("_is_self"), node.get("is_self"), False)),
        "os": first(node.get("OS"), node.get("os"), record.get("OS")),
        "client_version": first(
            node.get("ClientVersion"),
            node.get("client_version"),
            node.get("clientVersion"),
            node.get("Version"),
            record.get("ClientVersion"),
        ),
        "tags": tags,
        "user": first(
            nested_get(user_profile, "DisplayName"),
            nested_get(user_profile, "LoginName"),
            node.get("user") if isinstance(node.get("user"), str) else None,
        ),
        "relay": first(node.get("Relay"), node.get("relay"), record.get("Relay")),
        "active": first(node.get("Active"), node.get("active"), record.get("Active")),
        "exit_node": bool(
            first(node.get("ExitNode"), node.get("exit_node"), record.get("ExitNode"), False)
        ),
        "offers_exit_node": bool(
            first(
                node.get("ExitNodeOption"),
                node.get("offers_exit_node"),
                record.get("ExitNodeOption"),
                False,
            )
        ),
        "last_seen": first(
            node.get("LastSeen"),
            node.get("last_seen"),
            node.get("lastSeen"),
            record.get("LastSeen"),
        ),
        "key_expiry": first(
            node.get("KeyExpiry"),
            node.get("key_expiry"),
            node.get("expires"),
            record.get("KeyExpiry"),
        ),
        "endpoints": list_of_strings(
            first(node.get("Endpoints"), node.get("endpoints"), record.get("Addrs"), [])
        ),
        "ping": {
            "ok": ping.get("ok"),
            "latency_ms": first(ping.get("latency_ms"), ping.get("duration_ms")),
            "endpoint": first(ping.get("endpoint"), ping.get("via")),
        },
        "inspection_error": node.get("inspection_error"),
    }


def transform_tailnet(inventory: dict[str, Any]) -> dict[str, Any]:
    nodes = [normalize_tailscale_node(node) for node in tailscale_nodes(inventory)]
    nodes.sort(key=lambda item: (item["status"] != "online", str(item["name"] or "")))
    status_counts = Counter(str(node.get("status") or "unknown") for node in nodes)
    os_counts = Counter(str(node.get("os") or "unknown") for node in nodes)
    return {
        "schema_version": 1,
        "page": {
            "id": "tailnet",
            "title": "Tailnet",
            "description": "Tailscale devices, connectivity, ownership, and routing.",
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "source": inventory.get("metadata", {}),
        "summary": {
            "nodes": len(nodes),
            "online": status_counts.get("online", 0),
            "offline": status_counts.get("offline", 0),
            "exit_nodes": sum(
                bool(node["exit_node"] or node["offers_exit_node"]) for node in nodes
            ),
            "tagged": sum(bool(node["tags"]) for node in nodes),
            "by_status": dict(status_counts),
            "by_os": dict(os_counts),
        },
        "filters": {
            "statuses": sorted(status_counts),
            "operating_systems": sorted(os_counts),
            "tags": sorted({tag for node in nodes for tag in node["tags"]}),
        },
        "nodes": nodes,
    }


def relationship_index(inventory: dict[str, Any], kind: str) -> dict[str, dict[str, Any]]:
    relationships = nested_get(inventory, "relationships", kind)
    return {
        item["resource_uuid"]: item
        for item in list_of_dicts(relationships)
        if isinstance(item.get("resource_uuid"), str)
    }


def domains_for(resource: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    values.extend(list_of_strings(resource.get("domains")))
    values.extend(list_of_strings(resource.get("docker_compose_domains")))
    for key in ("fqdn", "domain"):
        value = resource.get(key)
        if isinstance(value, str):
            values.extend(part.strip() for part in value.split(","))
    return unique_strings(values)


def compose_value(resource: dict[str, Any]) -> tuple[str | None, str | None]:
    for field in COMPOSE_FIELDS:
        value = resource.get(field)
        if isinstance(value, str) and value.strip() and value != REDACTED:
            return field, value
    return None, None


def normalize_coolify_resource(
    resource: dict[str, Any],
    kind: str,
    relationships: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    resource_uuid = string(resource.get("uuid"))
    relation = relationships.get(resource_uuid or "", {})
    server = resource.get("server") if isinstance(resource.get("server"), dict) else {}
    destination = (
        resource.get("destination") if isinstance(resource.get("destination"), dict) else {}
    )
    containers = [
        {
            "uuid": item.get("uuid"),
            "name": first(item.get("human_name"), item.get("name")),
            "image": item.get("image"),
            "status": item.get("status"),
            "fqdn": item.get("fqdn"),
        }
        for key in ("applications", "databases")
        for item in list_of_dicts(resource.get(key))
    ]
    compose_field, compose = compose_value(resource)
    return {
        "uuid": resource_uuid,
        "name": resource.get("name"),
        "kind": kind.rstrip("s"),
        "type": first(
            resource.get("service_type"),
            resource.get("database_type"),
            resource.get("type"),
        ),
        "description": resource.get("description"),
        "status": resource.get("status") or "unknown",
        "project_uuid": first(resource.get("project_uuid"), relation.get("project_uuid")),
        "project_name": first(resource.get("project_name"), relation.get("project_name")),
        "environment_id": first(resource.get("environment_id"), relation.get("environment_id")),
        "environment_name": first(
            resource.get("environment_name"), relation.get("environment_name")
        ),
        "server_id": first(resource.get("server_id"), relation.get("server_id")),
        "server_uuid": first(server.get("uuid"), relation.get("server_uuid")),
        "server_name": server.get("name"),
        "destination_id": first(resource.get("destination_id"), relation.get("destination_id")),
        "destination_uuid": first(destination.get("uuid"), relation.get("destination_uuid")),
        "domains": domains_for(resource),
        "repository": resource.get("git_repository"),
        "branch": resource.get("git_branch"),
        "image": first(
            resource.get("image"),
            resource.get("docker_registry_image_name"),
        ),
        "build_pack": resource.get("build_pack"),
        "containers": containers,
        "compose_available": compose is not None,
        "compose_field": compose_field,
        "updated_at": resource.get("updated_at"),
    }


def transform_coolify(inventory: dict[str, Any]) -> dict[str, Any]:
    resources: list[dict[str, Any]] = []
    for kind in RESOURCE_KINDS:
        relations = relationship_index(inventory, kind)
        resources.extend(
            normalize_coolify_resource(resource, kind, relations)
            for resource in list_of_dicts(inventory.get(kind))
        )
    resources.sort(
        key=lambda item: (
            str(item.get("project_name") or ""),
            str(item.get("environment_name") or ""),
            str(item.get("name") or ""),
        )
    )

    grouped: dict[tuple[Any, Any], list[str]] = defaultdict(list)
    for resource in resources:
        grouped[(resource.get("project_uuid"), resource.get("environment_name"))].append(
            resource.get("uuid")
        )

    projects = []
    project_records = list_of_dicts(inventory.get("projects"))
    for project in project_records:
        environments = []
        for environment in list_of_dicts(project.get("environments")):
            key = (project.get("uuid"), environment.get("name"))
            environments.append(
                {
                    "id": environment.get("id"),
                    "name": environment.get("name"),
                    "description": environment.get("description"),
                    "resource_uuids": grouped.get(key, []),
                }
            )
        projects.append(
            {
                "uuid": project.get("uuid"),
                "name": project.get("name"),
                "description": project.get("description"),
                "environments": environments,
            }
        )

    statuses = Counter(str(item["status"]) for item in resources)
    kinds = Counter(str(item["kind"]) for item in resources)
    return {
        "schema_version": 1,
        "page": {
            "id": "coolify",
            "title": "Coolify",
            "description": "Projects, environments, applications, services, and databases.",
        },
        "generated_at": datetime.now(UTC).isoformat(),
        "source": inventory.get("metadata", {}),
        "summary": {
            "projects": len(projects),
            "environments": sum(len(project["environments"]) for project in projects),
            "resources": len(resources),
            "servers": len(list_of_dicts(inventory.get("servers"))),
            "by_status": dict(statuses),
            "by_kind": dict(kinds),
        },
        "filters": {
            "statuses": sorted(statuses),
            "kinds": sorted(kinds),
            "projects": [
                {"uuid": project["uuid"], "name": project["name"]} for project in projects
            ],
        },
        "projects": projects,
        "resources": resources,
        "servers": [
            {
                "uuid": server.get("uuid"),
                "name": server.get("name"),
                "description": server.get("description"),
                "status": first(
                    server.get("status"),
                    "online" if server.get("is_reachable") else "offline",
                ),
                "ip": server.get("ip"),
                "proxy_type": nested_get(server, "proxy", "type"),
                "is_reachable": server.get("is_reachable"),
                "is_usable": server.get("is_usable"),
            }
            for server in list_of_dicts(inventory.get("servers"))
        ],
        "warnings": inventory.get("warnings", []),
    }


def write_dashboard_outputs(
    output_dir: Path,
    name: str,
    transformed: dict[str, Any],
    output_format: str,
) -> list[Path]:
    paths = []
    suffixes = ("yaml", "json") if output_format == "both" else (output_format,)
    for suffix in suffixes:
        path = output_dir / f"{name}.{suffix}"
        write_document(path, transformed)
        paths.append(path)
    return paths


def dashboard_command(args: argparse.Namespace) -> list[Path]:
    outputs: list[Path] = []
    if args.tailscale and Path(args.tailscale).is_file():
        outputs.extend(
            write_dashboard_outputs(
                args.output_dir,
                "tailnet",
                transform_tailnet(load_document(args.tailscale)),
                args.format,
            )
        )
    elif args.tailscale:
        raise TransformError(f"Tailscale inventory not found: {args.tailscale}")
    if args.coolify and Path(args.coolify).is_file():
        outputs.extend(
            write_dashboard_outputs(
                args.output_dir,
                "coolify",
                transform_coolify(load_document(args.coolify)),
                args.format,
            )
        )
    elif args.coolify:
        raise TransformError(f"Coolify inventory not found: {args.coolify}")
    if not outputs:
        raise TransformError("dashboard requires a readable --tailscale and/or --coolify inventory")
    return outputs


def atomic_write_text(path: Path, content: str, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
    return True


def template_resource_dir(output_dir: Path, resource: dict[str, Any], kind: str) -> Path:
    resource_uuid = string(resource.get("uuid")) or "no-uuid"
    project = slugify(resource.get("project_name") or resource.get("project_uuid"), "unmapped")
    environment = slugify(resource.get("environment_name"), "unknown-environment")
    name = slugify(resource.get("name"), kind.rstrip("s"))
    return output_dir / project / environment / kind / f"{name}--{resource_uuid[:12]}"


def template_command(args: argparse.Namespace) -> list[Path]:
    inventory = load_document(args.coolify)
    manifest: list[dict[str, Any]] = []
    written: list[Path] = []

    for kind in ("services", "applications"):
        relations = relationship_index(inventory, kind)
        for raw_resource in list_of_dicts(inventory.get(kind)):
            normalized = normalize_coolify_resource(raw_resource, kind, relations)
            directory = template_resource_dir(args.output_dir, normalized, kind)
            compose_field, compose_text = compose_value(raw_resource)
            resource_uuid = normalized.get("uuid")
            entry = {
                **normalized,
                "directory": str(directory.relative_to(args.output_dir)),
                "api_endpoint": f"/api/v1/{kind}/{resource_uuid}" if resource_uuid else None,
                "compose_status": "available" if compose_text else "needs-fetch",
                "compose_source_field": compose_field,
            }
            manifest.append(entry)

            metadata_path = directory / "metadata.yaml"
            if not metadata_path.exists() or args.overwrite:
                write_document(metadata_path, entry)
                written.append(metadata_path)

            if compose_text:
                source_path = directory / "docker-compose.source.yaml"
                template_path = directory / "docker-compose.template.yaml"
                if atomic_write_text(source_path, compose_text.rstrip() + "\n", args.overwrite):
                    written.append(source_path)
                if atomic_write_text(
                    template_path,
                    copy.deepcopy(compose_text).rstrip() + "\n",
                    args.overwrite,
                ):
                    written.append(template_path)

    manifest.sort(
        key=lambda item: (
            str(item.get("project_name") or ""),
            str(item.get("environment_name") or ""),
            str(item.get("name") or ""),
        )
    )
    manifest_document = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": str(args.coolify),
        "summary": {
            "resources": len(manifest),
            "compose_available": sum(item["compose_status"] == "available" for item in manifest),
            "needs_fetch": sum(item["compose_status"] == "needs-fetch" for item in manifest),
        },
        "instructions": {
            "source_file": "Never modify docker-compose.source.yaml.",
            "template_file": "Apply sidecars and other policies to docker-compose.template.yaml.",
            "needs_fetch": (
                "Fetch the resource's detail from api_endpoint, then supply "
                "docker_compose_raw or docker_compose in a non-public inventory."
            ),
        },
        "resources": manifest,
    }
    manifest_path = args.output_dir / "manifest.yaml"
    write_document(manifest_path, manifest_document)
    written.append(manifest_path)
    return written


def main() -> int:
    args = parse_args()
    try:
        outputs = dashboard_command(args) if args.command == "dashboard" else template_command(args)
    except (OSError, TransformError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Wrote {len(outputs)} file(s):")
    for path in outputs:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
