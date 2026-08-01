"""Docker inventory probes for backup discovery."""

from __future__ import annotations

import json
from typing import Any

from serverops.models import Target
from serverops.utils.command import run_read_only
from serverops.utils.secrets import redact_value

DB_IMAGE_HINTS = (
    "postgres",
    "postgresql",
    "mysql",
    "mariadb",
    "mongo",
    "mongodb",
    "redis",
    "valkey",
)


def _parse_json_lines(stdout: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
        elif isinstance(value, list):
            items.extend(item for item in value if isinstance(item, dict))
    return items


def classify_database_engine(image: str | None, env_names: list[str] | None = None) -> str | None:
    """Public helper: map image/env hints to a database engine name."""
    return _classify_database(image, env_names or [])


def _classify_database(image: str | None, env_names: list[str]) -> str | None:
    blob = " ".join([image or "", *env_names]).lower()
    for hint in DB_IMAGE_HINTS:
        if hint in blob:
            if hint in {"postgres", "postgresql"}:
                return "postgresql"
            if hint in {"mysql"}:
                return "mysql"
            if hint in {"mariadb"}:
                return "mariadb"
            if hint in {"mongo", "mongodb"}:
                return "mongodb"
            if hint in {"redis", "valkey"}:
                return "redis"
    return None


def discover_docker(target: Target, timeout: int) -> dict[str, Any]:
    """Read-only Docker discovery for containers, volumes, and mounts."""
    result: dict[str, Any] = {
        "available": False,
        "version": None,
        "containers": [],
        "volumes": [],
        "warnings": [],
    }

    version = run_read_only(
        ["docker", "version", "--format", "{{json .}}"],
        target=target,
        timeout=timeout,
    )
    if version.returncode != 0:
        result["warnings"].append(version.stderr or "docker version failed")
        return result
    result["available"] = True
    try:
        result["version"] = json.loads(version.stdout) if version.stdout else None
    except json.JSONDecodeError:
        result["version"] = {"raw": version.stdout}

    ps = run_read_only(
        ["docker", "ps", "--all", "--format", "{{json .}}"],
        target=target,
        timeout=timeout,
    )
    containers = _parse_json_lines(ps.stdout) if ps.returncode == 0 else []
    if ps.returncode != 0:
        result["warnings"].append(ps.stderr or "docker ps failed")

    detailed: list[dict[str, Any]] = []
    for summary in containers:
        name = summary.get("Names") or summary.get("names") or summary.get("ID")
        inspect = run_read_only(
            ["docker", "inspect", str(name)],
            target=target,
            timeout=timeout,
        )
        payload: dict[str, Any] = {
            "name": name,
            "id": summary.get("ID"),
            "image": summary.get("Image"),
            "status": summary.get("Status"),
            "labels": {},
            "mounts": [],
            "env_names": [],
            "probable_database": None,
            "compose_project": None,
            "compose_service": None,
        }
        if inspect.returncode == 0 and inspect.stdout:
            try:
                inspected = json.loads(inspect.stdout)
                record = inspected[0] if isinstance(inspected, list) and inspected else inspected
            except json.JSONDecodeError:
                record = {}
            if isinstance(record, dict):
                config = record.get("Config") if isinstance(record.get("Config"), dict) else {}
                labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
                env_raw = config.get("Env") if isinstance(config.get("Env"), list) else []
                env_names = []
                for item in env_raw:
                    if isinstance(item, str) and "=" in item:
                        env_names.append(item.split("=", 1)[0])
                mounts = []
                for mount in record.get("Mounts") or []:
                    if not isinstance(mount, dict):
                        continue
                    mounts.append(
                        {
                            "type": mount.get("Type"),
                            "name": mount.get("Name"),
                            "source": mount.get("Source"),
                            "destination": mount.get("Destination"),
                            "rw": mount.get("RW"),
                        }
                    )
                payload.update(
                    {
                        "labels": labels,
                        "mounts": mounts,
                        "env_names": env_names,
                        "compose_project": labels.get("com.docker.compose.project"),
                        "compose_service": labels.get("com.docker.compose.service"),
                        "probable_database": _classify_database(
                            str(config.get("Image") or summary.get("Image") or ""),
                            env_names,
                        ),
                    }
                )
        else:
            payload["probable_database"] = _classify_database(str(summary.get("Image") or ""), [])
        detailed.append(redact_value(payload))
    result["containers"] = detailed

    volumes = run_read_only(
        ["docker", "volume", "ls", "--format", "{{json .}}"],
        target=target,
        timeout=timeout,
    )
    if volumes.returncode == 0:
        result["volumes"] = _parse_json_lines(volumes.stdout)
    else:
        result["warnings"].append(volumes.stderr or "docker volume ls failed")

    return redact_value(result)
