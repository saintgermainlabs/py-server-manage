#!/usr/bin/env python3
"""Build a detailed YAML inventory using only the official Tailscale CLI."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from serverops.paths import inventory_path

try:
    import yaml
except ImportError:
    sys.exit(
        "PyYAML is required. Install it with: uv tool run --from PyYAML python "
        "tailscale_inventory.py  (or: python3 -m pip install PyYAML)"
    )


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def resolve_tailscale_binary(name: str) -> str | None:
    """Resolve the official Tailscale CLI, skipping Python entry-point shims."""
    if Path(name).is_absolute() or "/" in name or name.startswith("./"):
        path = Path(name)
        return str(path) if path.is_file() and os.access(path, os.X_OK) else None

    # Prefer well-known system locations before PATH so a same-named Python
    # package console script in .venv/bin cannot shadow the real CLI.
    for candidate in ("/usr/bin/tailscale", "/usr/local/bin/tailscale", "/bin/tailscale"):
        if name == "tailscale" and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    found = shutil.which(name)
    if not found:
        return None
    try:
        head = Path(found).read_text(encoding="utf-8", errors="ignore")[:120]
    except OSError:
        return found
    if "python" in head.lower() and "tailscale" in Path(found).parts:
        # Likely a PyPI console_script wrapper, not the Go CLI.
        for candidate in ("/usr/bin/tailscale", "/usr/local/bin/tailscale", "/bin/tailscale"):
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return found


def command_result(
    base: list[str],
    args: list[str],
    timeout: float,
    *,
    expect_json: bool = False,
) -> dict[str, Any]:
    """Run a read-only CLI command and preserve success or failure details."""
    command = [*base, *args]
    started = time.monotonic()
    try:
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "command": command,
            "error": "timeout",
            "timeout_seconds": timeout,
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
            "duration_seconds": round(time.monotonic() - started, 3),
        }
    except OSError as exc:
        return {
            "ok": False,
            "command": command,
            "error": str(exc),
            "duration_seconds": round(time.monotonic() - started, 3),
        }

    result: dict[str, Any] = {
        "ok": process.returncode == 0,
        "command": command,
        "exit_code": process.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
    }
    stdout = process.stdout.strip()
    stderr = process.stderr.strip()

    if expect_json and stdout:
        try:
            result["data"] = json.loads(stdout)
        except json.JSONDecodeError as exc:
            result["ok"] = False
            result["parse_error"] = str(exc)
            result["stdout"] = stdout
    elif stdout:
        result["stdout"] = stdout
    if stderr:
        result["stderr"] = stderr
    return result


def first_ip(record: dict[str, Any]) -> str | None:
    values = record.get("TailscaleIPs") or record.get("Addresses") or []
    return str(values[0]) if values else None


def node_name(record: dict[str, Any], fallback: str) -> str:
    return str(
        record.get("HostName")
        or record.get("DNSName", "").rstrip(".")
        or record.get("ID")
        or fallback
    )


def inspect_node(
    base: list[str],
    key: str,
    record: dict[str, Any],
    timeout: float,
    ping_count: int,
    run_ping: bool,
) -> dict[str, Any]:
    address = first_ip(record)
    item: dict[str, Any] = {
        "name": node_name(record, key),
        "primary_tailscale_ip": address,
        "status": record,
    }
    if not address:
        item["inspection_error"] = "No Tailscale IP was present in status data"
        return item

    item["whois"] = command_result(base, ["whois", "--json", address], timeout, expect_json=True)
    if run_ping:
        item["ping"] = command_result(
            base,
            [
                "ping",
                f"--c={ping_count}",
                f"--timeout={timeout}s",
                "--until-direct=false",
                address,
            ],
            timeout * ping_count + 2,
        )
    return item


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Export a read-only Tailscale node inventory to YAML."
    )
    result.add_argument(
        "-o",
        "--output",
        type=Path,
        default=inventory_path("tailscale-inventory.yaml"),
        help="Output YAML path (default: data/inventory/tailscale-inventory.yaml).",
    )
    result.add_argument("--tailscale-bin", default="tailscale")
    result.add_argument("--socket", help="Optional tailscaled Unix socket path")
    result.add_argument("--timeout", type=float, default=5.0)
    result.add_argument("--ping-count", type=int, default=2)
    result.add_argument("--no-ping", action="store_true")
    result.add_argument("--workers", type=int, default=8)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.timeout <= 0 or args.ping_count <= 0 or args.workers <= 0:
        sys.exit("--timeout, --ping-count, and --workers must be greater than zero")

    binary = resolve_tailscale_binary(args.tailscale_bin)
    if not binary:
        sys.exit(f"Tailscale CLI not found in PATH: {args.tailscale_bin}")

    base = [binary]
    if args.socket:
        base.extend(["--socket", args.socket])

    status = command_result(base, ["status", "--json"], args.timeout, expect_json=True)
    if not status.get("ok") or not isinstance(status.get("data"), dict):
        print(yaml.safe_dump({"status": status}, sort_keys=False), file=sys.stderr)
        sys.exit("Unable to obtain `tailscale status --json`; is tailscaled running?")

    status_data = status["data"]
    peer_map = status_data.get("Peer") or {}
    self_record = status_data.get("Self") or {}
    records: list[tuple[str, dict[str, Any], bool]] = []
    if self_record:
        records.append(("self", self_record, True))
    records.extend((str(key), value, False) for key, value in peer_map.items())

    nodes: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                inspect_node,
                base,
                key,
                record,
                args.timeout,
                args.ping_count,
                not args.no_ping and not is_self,
            ): (key, record)
            for key, record, is_self in records
        }
        for future in concurrent.futures.as_completed(futures):
            key, record = futures[future]
            try:
                nodes.append(future.result())
            except Exception as exc:  # Keep one bad peer from losing the inventory.
                nodes.append(
                    {
                        "name": node_name(record, key),
                        "status": record,
                        "inspection_error": f"{type(exc).__name__}: {exc}",
                    }
                )
    nodes.sort(
        key=lambda item: (
            str(item.get("name", "")).lower(),
            str(item.get("primary_tailscale_ip", "")),
        )
    )

    local_checks = {
        "version": command_result(
            base, ["version", "--daemon", "--json"], args.timeout, expect_json=True
        ),
        "netcheck": command_result(
            base, ["netcheck", "--format=json"], max(args.timeout, 15), expect_json=True
        ),
        "dns": command_result(
            base, ["dns", "status", "--all", "--json"], args.timeout, expect_json=True
        ),
        "exit_nodes": command_result(base, ["exit-node", "list"], args.timeout),
        "serve": command_result(
            base, ["serve", "status", "--json"], args.timeout, expect_json=True
        ),
        "app_connector_routes": command_result(base, ["appc-routes", "--all"], args.timeout),
    }

    inventory = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "collector": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "tailscale_binary": binary,
            "socket": args.socket,
        },
        "summary": {
            "node_count": len(nodes),
            "peer_count": len(peer_map),
            "online_peer_count": sum(1 for peer in peer_map.values() if peer.get("Online") is True),
        },
        "tailnet": {
            "current_tailnet": status_data.get("CurrentTailnet"),
            "backend_state": status_data.get("BackendState"),
            "health": status_data.get("Health"),
            "magic_dns_suffix": status_data.get("MagicDNSSuffix"),
            "tun": status_data.get("TUN"),
            "user_profiles": status_data.get("User"),
        },
        "local_checks": local_checks,
        "nodes": nodes,
        "raw_status": status,
    }

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        yaml.safe_dump(
            inventory,
            handle,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
            width=120,
        )
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(f"Wrote {len(nodes)} nodes to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
