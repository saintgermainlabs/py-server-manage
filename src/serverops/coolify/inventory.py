#!/usr/bin/env python3
"""Export a detailed inventory from a Coolify instance using Coolipy.

Required environment variables:
    COOLIFY_URL=https://coolify.example.com
    COOLIFY_API_KEY=your-api-token

Examples:
    uv run --with coolipy python src/coolify_inventory.py
    uv run --with coolipy python src/coolify_inventory.py -o inventory.json
    uv run --with coolipy --with pyyaml python src/coolify_inventory.py \
        -o inventory.yaml
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from serverops.paths import inventory_path

try:
    from coolipy import Coolipy
except ImportError:
    print(
        "coolipy is not installed. Run this script with:\n"
        "  uv run --with coolipy python src/coolify_inventory.py",
        file=sys.stderr,
    )
    raise SystemExit(2) from None


SENSITIVE_KEY_RE = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|private[_-]?key|credential)",
    re.IGNORECASE,
)
COMPOSE_KEY_RE = re.compile(
    r"^(docker_compose|docker_compose_raw|compose|compose_raw)$", re.IGNORECASE
)
URL_PASSWORD_RE = re.compile(r"(://[^:/@\s]+:)([^@\s]+)(@)")


class InventoryError(RuntimeError):
    """Raised when the Coolify API cannot provide a requested resource."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Export Coolify projects, environments, services, applications, "
            "databases, resources, and servers, including UUID relationships."
        )
    )
    parser.add_argument(
        "--url",
        default=os.getenv("COOLIFY_URL"),
        help="Coolify base URL (or set COOLIFY_URL).",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("COOLIFY_API_KEY")
        or os.getenv("COOLIFY_API_TOKEN")
        or os.getenv("COOLIFY_TOKEN"),
        help="Coolify API token (or set COOLIFY_API_KEY).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=inventory_path("coolify-inventory.yaml"),
        help="Output .json, .yaml, or .yml file (default: data/inventory/coolify-inventory.yaml).",
    )
    parser.add_argument(
        "--include-sensitive",
        action="store_true",
        help=("Do not redact secret-looking fields or raw Compose content. Use with care."),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Stop if any optional detail endpoint fails.",
    )
    args = parser.parse_args(argv)
    if not args.url:
        parser.error("--url or COOLIFY_URL is required")
    if not args.api_key:
        parser.error("--api-key or COOLIFY_API_KEY is required")
    return args


def make_client(url: str, api_key: str) -> Coolipy:
    candidate = url if "://" in url else f"https://{url}"
    parsed = urlparse(candidate.rstrip("/"))
    if not parsed.hostname:
        raise InventoryError(f"Invalid Coolify URL: {url!r}")
    if parsed.path not in ("", "/"):
        raise InventoryError(
            f"COOLIFY_URL must be the instance base URL, without /api/v1 or another path: {url!r}"
        )

    protocol = parsed.scheme or "https"
    default_port = 443 if protocol == "https" else 80
    return Coolipy(
        coolify_api_key=api_key,
        coolify_endpoint=parsed.hostname,
        coolify_port=parsed.port or default_port,
        omit_port=parsed.port is None,
        http_protocol=protocol,
    )


def jsonify(value: Any) -> Any:
    """Turn Coolipy models and common Python objects into JSON-safe values."""
    if dataclasses.is_dataclass(value):
        return {
            field.name: jsonify(getattr(value, field.name)) for field in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(key): jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonify(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "__dict__"):
        return {
            str(key): jsonify(item) for key, item in vars(value).items() if not key.startswith("_")
        }
    return str(value)


def redact(value: Any, include_sensitive: bool = False) -> Any:
    if include_sensitive:
        return value
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            if SENSITIVE_KEY_RE.search(key) or COMPOSE_KEY_RE.search(key):
                clean[key] = "[REDACTED]"
            else:
                clean[key] = redact(item)
        return clean
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return URL_PASSWORD_RE.sub(r"\1[REDACTED]\3", value)
    return value


def raw_get(client: Coolipy, path: str, *, required: bool = True) -> Any:
    """Use Coolipy's HTTP response wrapper without lossy model conversion."""
    response = client._http.get(path)  # noqa: SLF001 - Coolipy has no public raw API.
    if response.status_code not in (200, 201):
        message = f"GET {path} returned HTTP {response.status_code}: {response.data!r}"
        if required:
            raise InventoryError(message)
        raise InventoryError(message)
    return jsonify(response.data)


def as_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def uuid_of(value: Any) -> str | None:
    return value.get("uuid") if isinstance(value, dict) else None


def build_environment_index(
    projects: list[dict[str, Any]],
) -> dict[int | str, dict[str, Any]]:
    index: dict[int | str, dict[str, Any]] = {}
    for project in projects:
        for environment in as_list(project.get("environments")):
            environment_id = environment.get("id")
            if environment_id is None:
                continue
            index[environment_id] = {
                "project_uuid": project.get("uuid"),
                "project_id": project.get("id"),
                "project_name": project.get("name"),
                "environment_id": environment_id,
                "environment_name": environment.get("name"),
            }
    return index


def relationship_for(
    item: dict[str, Any], environment_index: dict[int | str, dict[str, Any]]
) -> dict[str, Any]:
    relation = dict(environment_index.get(item.get("environment_id"), {}))
    destination = item.get("destination")
    server = item.get("server")
    relation.update(
        {
            "resource_uuid": item.get("uuid"),
            "environment_id": item.get("environment_id"),
            "server_id": item.get("server_id"),
            "server_uuid": uuid_of(server),
            "destination_id": item.get("destination_id"),
            "destination_uuid": uuid_of(destination),
        }
    )
    if not relation.get("server_uuid") and isinstance(destination, dict):
        relation["server_uuid"] = uuid_of(destination.get("server"))
    return relation


def fetch_details(
    client: Coolipy,
    collection: list[dict[str, Any]],
    endpoint: str,
    warnings: list[str],
    strict: bool,
) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for summary in collection:
        resource_uuid = summary.get("uuid")
        if not resource_uuid:
            details.append(summary)
            continue
        try:
            detail = raw_get(client, f"/{endpoint}/{resource_uuid}")
            details.append(detail if isinstance(detail, dict) else summary)
        except InventoryError as exc:
            if strict:
                raise
            warnings.append(str(exc))
            details.append(summary)
    return details


def collect_inventory(client: Coolipy, strict: bool = False) -> dict[str, Any]:
    warnings: list[str] = []
    version = raw_get(client, "/version")
    projects = as_list(raw_get(client, "/projects"))

    # Project detail responses normally contain the complete environment lists.
    project_details = fetch_details(client, projects, "projects", warnings, strict)
    environment_index = build_environment_index(project_details)

    collections: dict[str, list[dict[str, Any]]] = {}
    for name, endpoint in (
        ("services", "services"),
        ("applications", "applications"),
        ("databases", "databases"),
        ("servers", "servers"),
    ):
        summaries = as_list(raw_get(client, f"/{endpoint}"))
        collections[name] = fetch_details(client, summaries, endpoint, warnings, strict)

    try:
        resources = as_list(raw_get(client, "/resources"))
    except InventoryError as exc:
        if strict:
            raise
        warnings.append(str(exc))
        resources = []

    relationships = {
        name: [relationship_for(item, environment_index) for item in items]
        for name, items in {
            "services": collections["services"],
            "applications": collections["applications"],
            "databases": collections["databases"],
            "resources": resources,
        }.items()
    }

    environments = [
        {
            **environment,
            "project_uuid": project.get("uuid"),
            "project_name": project.get("name"),
        }
        for project in project_details
        for environment in as_list(project.get("environments"))
    ]

    return {
        "metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "coolify_version": version,
            "generator": "coolify_inventory.py",
            "coolipy_version": "0.0.8",
        },
        "summary": {
            "projects": len(project_details),
            "environments": len(environments),
            "services": len(collections["services"]),
            "service_containers": sum(
                len(as_list(service.get("applications"))) + len(as_list(service.get("databases")))
                for service in collections["services"]
            ),
            "applications": len(collections["applications"]),
            "databases": len(collections["databases"]),
            "resources": len(resources),
            "servers": len(collections["servers"]),
        },
        "projects": project_details,
        "environments": environments,
        "services": collections["services"],
        "applications": collections["applications"],
        "databases": collections["databases"],
        "resources": resources,
        "servers": collections["servers"],
        "relationships": relationships,
        "warnings": warnings,
    }


def write_inventory(path: Path, inventory: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = path.suffix.lower()
    if suffix == ".json":
        path.write_text(
            json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise InventoryError(
                "YAML output requires PyYAML. Run with both dependencies:\n"
                "  uv run --with coolipy --with pyyaml python "
                "src/coolify_inventory.py -o coolify_inventory.yaml"
            ) from None
        path.write_text(
            yaml.safe_dump(inventory, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return
    raise InventoryError("Output filename must end in .json, .yaml, or .yml")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        client = make_client(args.url, args.api_key)
        inventory = collect_inventory(client, strict=args.strict)
        inventory = redact(inventory, include_sensitive=args.include_sensitive)
        write_inventory(args.output, inventory)
    except (InventoryError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    summary = inventory["summary"]
    print(
        f"Wrote {args.output}: {summary['services']} services, "
        f"{summary['applications']} applications, "
        f"{summary['databases']} databases across "
        f"{summary['projects']} projects."
    )
    if inventory["warnings"]:
        print(
            f"Completed with {len(inventory['warnings'])} warning(s); "
            "see the warnings section in the inventory.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
