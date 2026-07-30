#!/usr/bin/env python3
"""Export a read-only inventory of a Tailscale tailnet through API v2.

Authentication (choose one):

  export TAILSCALE_API_KEY='tskey-api-...'

or:

  export TAILSCALE_OAUTH_CLIENT_ID='...'
  export TAILSCALE_OAUTH_CLIENT_SECRET='tskey-client-...'

The tailnet defaults to "-" (the token's default tailnet). Override it with
TAILSCALE_TAILNET or --tailnet. Output is YAML when PyYAML is installed and
JSON otherwise.

Profiles:

  verbose    Complete inventory (default).
  dashboard  Minimal app/node data suitable for building a links dashboard.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from serverops.paths import inventory_path

API_BASE = "https://api.tailscale.com/api/v2"
DEFAULT_TIMEOUT = 30


@dataclass(frozen=True)
class Endpoint:
    name: str
    path: str
    optional: bool = True


TAILNET_ENDPOINTS = (
    Endpoint("devices", "/tailnet/{tailnet}/devices?fields=all", False),
    Endpoint("users", "/tailnet/{tailnet}/users"),
    Endpoint("keys", "/tailnet/{tailnet}/keys"),
    Endpoint("policy", "/tailnet/{tailnet}/acl"),
    Endpoint("dns_configuration", "/tailnet/{tailnet}/dns/configuration"),
    Endpoint("dns_nameservers", "/tailnet/{tailnet}/dns/nameservers"),
    Endpoint("dns_preferences", "/tailnet/{tailnet}/dns/preferences"),
    Endpoint("dns_search_paths", "/tailnet/{tailnet}/dns/searchpaths"),
    Endpoint("dns_split", "/tailnet/{tailnet}/dns/split-dns"),
    Endpoint("settings", "/tailnet/{tailnet}/settings"),
    Endpoint("contacts", "/tailnet/{tailnet}/contacts"),
    Endpoint("user_invites", "/tailnet/{tailnet}/user-invites"),
    Endpoint("webhooks", "/tailnet/{tailnet}/webhooks"),
    Endpoint("posture_integrations", "/tailnet/{tailnet}/posture/integrations"),
    Endpoint("services", "/tailnet/{tailnet}/services"),
    Endpoint("oauth_apps", "/tailnet/{tailnet}/oauth-apps"),
)

LOG_ENDPOINTS = (
    Endpoint("configuration_audit_logs", "/tailnet/{tailnet}/logging/configuration"),
    Endpoint("network_flow_logs", "/tailnet/{tailnet}/logging/network"),
    Endpoint(
        "configuration_log_stream_status",
        "/tailnet/{tailnet}/logging/configuration/stream/status",
    ),
    Endpoint("configuration_log_stream", "/tailnet/{tailnet}/logging/configuration/stream"),
    Endpoint(
        "network_log_stream_status",
        "/tailnet/{tailnet}/logging/network/stream/status",
    ),
    Endpoint("network_log_stream", "/tailnet/{tailnet}/logging/network/stream"),
)


class APIError(RuntimeError):
    def __init__(self, status: int, path: str, message: str):
        super().__init__(f"HTTP {status} for {path}: {message}")
        self.status = status
        self.path = path
        self.message = message


class TailscaleAPI:
    def __init__(
        self,
        token: str,
        *,
        timeout: int = DEFAULT_TIMEOUT,
        retries: int = 3,
    ) -> None:
        self.token = token
        self.timeout = timeout
        self.retries = retries

    def get(self, path: str) -> Any:
        url = f"{API_BASE}{path}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "User-Agent": "tailscale-api-inventory/1.1",
            },
        )

        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                    if not raw:
                        return None
                    content_type = response.headers.get("Content-Type", "")
                    if "json" in content_type or raw.lstrip()[:1] in (b"{", b"["):
                        return json.loads(raw)
                    return raw.decode("utf-8", errors="replace")
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    time.sleep(min(delay, 30))
                    continue
                try:
                    detail = json.loads(body).get("message", body)
                except (json.JSONDecodeError, AttributeError):
                    detail = body
                raise APIError(exc.code, path, str(detail).strip()) from exc
            except urllib.error.URLError as exc:
                if attempt < self.retries:
                    time.sleep(2**attempt)
                    continue
                raise RuntimeError(f"Request failed for {path}: {exc.reason}") from exc

        raise AssertionError("unreachable")


def oauth_token(client_id: str, client_secret: str, timeout: int) -> str:
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("ascii")
    request = urllib.request.Request(
        f"{API_BASE}/oauth/token",
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OAuth token request failed (HTTP {exc.code}): {detail}") from exc
    token = result.get("access_token")
    if not token:
        raise RuntimeError("OAuth response did not contain access_token")
    return str(token)


def first_list(value: Any, *keys: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        for key in keys:
            items = value.get(key)
            if isinstance(items, list):
                return [item for item in items if isinstance(item, dict)]
    return []


def item_id(item: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value)
    return None


def safe_component(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def collect_endpoint(
    api: TailscaleAPI, endpoint: Endpoint, tailnet: str
) -> tuple[str, Any, dict[str, Any] | None]:
    path = endpoint.path.format(tailnet=safe_component(tailnet))
    try:
        return endpoint.name, api.get(path), None
    except APIError as exc:
        if not endpoint.optional:
            raise
        return (
            endpoint.name,
            None,
            {
                "status": exc.status,
                "message": exc.message,
                "path": exc.path,
            },
        )


def parallel_get(
    api: TailscaleAPI,
    requests: Iterable[tuple[str, str]],
    workers: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    values: dict[str, Any] = {}
    errors: dict[str, Any] = {}

    def fetch(name_path: tuple[str, str]) -> tuple[str, Any, dict[str, Any] | None]:
        name, path = name_path
        try:
            return name, api.get(path), None
        except APIError as exc:
            return (
                name,
                None,
                {
                    "status": exc.status,
                    "message": exc.message,
                    "path": exc.path,
                },
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        for name, value, error in executor.map(fetch, list(requests)):
            if error:
                errors[name] = error
            else:
                values[name] = value
    return values, errors


def collect_details(
    api: TailscaleAPI,
    inventory: dict[str, Any],
    tailnet: str,
    workers: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    requests: list[tuple[str, str]] = []

    devices = first_list(inventory.get("devices"), "devices")
    for device in devices:
        device_id = item_id(device, "id", "nodeId", "deviceId")
        if not device_id:
            continue
        encoded = safe_component(device_id)
        requests.extend(
            (
                (f"devices/{device_id}/record", f"/device/{encoded}"),
                (f"devices/{device_id}/routes", f"/device/{encoded}/routes"),
                (f"devices/{device_id}/posture_attributes", f"/device/{encoded}/attributes"),
                (f"devices/{device_id}/invites", f"/device/{encoded}/device-invites"),
            )
        )

    users = first_list(inventory.get("users"), "users")
    for user in users:
        user_id = item_id(user, "id", "userId")
        if user_id:
            requests.append((f"users/{user_id}", f"/users/{safe_component(user_id)}"))

    keys = first_list(inventory.get("keys"), "keys")
    for key in keys:
        key_id = item_id(key, "id", "keyId")
        if key_id:
            requests.append(
                (
                    f"keys/{key_id}",
                    f"/tailnet/{safe_component(tailnet)}/keys/{safe_component(key_id)}",
                )
            )

    webhooks = first_list(inventory.get("webhooks"), "webhooks")
    for webhook in webhooks:
        webhook_id = item_id(webhook, "id", "endpointId")
        if webhook_id:
            requests.append((f"webhooks/{webhook_id}", f"/webhooks/{safe_component(webhook_id)}"))

    integrations = first_list(
        inventory.get("posture_integrations"), "integrations", "postureIntegrations"
    )
    for integration in integrations:
        integration_id = item_id(integration, "id", "integrationId")
        if integration_id:
            requests.append(
                (
                    f"posture_integrations/{integration_id}",
                    f"/posture/integrations/{safe_component(integration_id)}",
                )
            )

    oauth_apps = first_list(inventory.get("oauth_apps"), "oauthApps", "apps")
    for app in oauth_apps:
        app_id = item_id(app, "id", "appId", "clientId")
        if app_id:
            requests.append(
                (
                    f"oauth_apps/{app_id}",
                    f"/tailnet/{safe_component(tailnet)}/oauth-apps/{safe_component(app_id)}",
                )
            )

    services = first_list(inventory.get("services"), "services")
    for service in services:
        service_name = item_id(service, "name", "serviceName")
        if not service_name:
            continue
        encoded = safe_component(service_name)
        requests.extend(
            (
                (
                    f"services/{service_name}/record",
                    f"/tailnet/{safe_component(tailnet)}/services/{encoded}",
                ),
                (
                    f"services/{service_name}/devices",
                    f"/tailnet/{safe_component(tailnet)}/services/{encoded}/devices",
                ),
            )
        )

    return parallel_get(api, requests, workers)


def nest_details(flat: dict[str, Any]) -> dict[str, Any]:
    root: dict[str, Any] = {}
    for compound_key, value in flat.items():
        cursor = root
        parts = compound_key.split("/")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return root


def redact_secrets(value: Any) -> Any:
    secret_names = {
        "secret",
        "clientsecret",
        "client_secret",
        "key",
        "privatekey",
        "private_key",
        "webhooksecret",
    }
    if isinstance(value, dict):
        result = {}
        for key, child in value.items():
            if key.lower() in secret_names and isinstance(child, str) and child:
                result[key] = "[REDACTED]"
            else:
                result[key] = redact_secrets(child)
        return result
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value


def load_dashboard_config(path: pathlib.Path | None) -> dict[str, dict[str, Any]]:
    """Load optional per-app dashboard settings from YAML or JSON."""
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            value = json.loads(text)
        else:
            try:
                import yaml  # type: ignore[import-not-found]
            except ImportError as exc:
                raise RuntimeError(
                    "A YAML dashboard config needs PyYAML; use JSON or install pyyaml."
                ) from exc
            value = yaml.safe_load(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read dashboard config {path}: {exc}") from exc

    if value is None:
        return {}
    if not isinstance(value, dict):
        raise RuntimeError("Dashboard config must be a mapping.")
    apps = value.get("apps", value)
    if not isinstance(apps, dict):
        raise RuntimeError("Dashboard config 'apps' must be a mapping.")
    return {str(name): settings for name, settings in apps.items() if isinstance(settings, dict)}


def dashboard_inventory(
    devices_response: Any,
    config: dict[str, dict[str, Any]],
    only_ui: bool = False,
) -> dict[str, Any]:
    """Reduce the devices response to stable dashboard-relevant fields."""
    apps: dict[str, dict[str, Any]] = {}
    devices = first_list(devices_response, "devices")

    for device in sorted(
        devices,
        key=lambda item: str(item.get("hostname") or item.get("name") or ""),
    ):
        hostname = str(device.get("hostname") or "").strip()
        dns_name = str(device.get("name") or "").rstrip(".")
        app_name = hostname or dns_name.split(".", 1)[0]
        if not app_name:
            continue

        settings = config.get(app_name, {})
        if settings.get("enabled", True) is False:
            continue

        app: dict[str, Any] = {}
        for field in ("id", "nodeId", "hostname"):
            if device.get(field) is not None:
                app[field] = device[field]
        if dns_name:
            app["name"] = dns_name
        if settings.get("url"):
            app["url"] = str(settings["url"])

        addresses = device.get("addresses")
        if isinstance(addresses, list) and addresses:
            app["addresses"] = addresses
        tags = device.get("tags")
        if isinstance(tags, list) and tags:
            app["tags"] = tags

        # Optional presentation metadata is copied only when explicitly configured.
        for field in ("title", "description", "icon", "category", "has_ui", "ui_url"):
            if settings.get(field) is not None:
                app[field] = settings[field]

        # Filter by has_ui if the option is enabled.
        # This happens AFTER other settings are applied, but BEFORE the app is added.
        if only_ui and not settings.get("has_ui") and not settings.get("ui_url"):
            continue

        key = str(settings.get("key") or app_name)
        if key in apps:
            suffix = str(device.get("id") or device.get("nodeId") or len(apps) + 1)
            key = f"{key}-{suffix}"
        apps[key] = app

    return {"tailnet": {"apps": apps}}


def write_output(data: dict[str, Any], output: pathlib.Path, fmt: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "yaml":
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "YAML output needs PyYAML: install it with `uv pip install pyyaml`, "
                "or use --format json"
            ) from exc
        text = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    output.write_text(text, encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a read-only, tailnet-wide Tailscale API inventory."
    )
    parser.add_argument(
        "profile",
        nargs="?",
        choices=("verbose", "dashboard"),
        default="verbose",
        help="Output profile (default: verbose).",
    )
    parser.add_argument(
        "--profile",
        dest="profile_option",
        choices=("verbose", "dashboard"),
        help="Output profile; alternative to the positional profile argument.",
    )
    parser.add_argument(
        "--dashboard-config",
        type=pathlib.Path,
        help="Optional YAML/JSON file containing app URL and presentation overrides.",
    )
    parser.add_argument(
        "--tailnet",
        default=os.environ.get("TAILSCALE_TAILNET", "-"),
        help='Organization/tailnet identifier; default "-" uses the token default.',
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="Output file (default: a timestamped file under data/).",
    )
    parser.add_argument(
        "--format",
        choices=("yaml", "json"),
        default="yaml",
        help="Output format (default: yaml).",
    )
    parser.add_argument(
        "--include-logs",
        action="store_true",
        help="Verbose only: request audit/network logs and streaming configuration.",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Verbose only: skip per-device/user/key/webhook/service detail calls.",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Verbose only: do not redact secret-like response fields (not recommended).",
    )
    parser.add_argument(
        "--only-ui",
        action="store_true",
        help="Dashboard only: include only devices with UI overrides in the dashboard config.",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    if args.profile_option:
        if args.profile != "verbose" and args.profile != args.profile_option:
            parser.error("profile specified twice with different values")
        args.profile = args.profile_option
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = os.environ.get("TAILSCALE_API_KEY")
    client_id = os.environ.get("TAILSCALE_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("TAILSCALE_OAUTH_CLIENT_SECRET")

    if api_key:
        token = api_key
        auth_method = "api_key"
    elif client_id and client_secret:
        try:
            token = oauth_token(client_id, client_secret, args.timeout)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        auth_method = "oauth_client_credentials"
    else:
        print(
            "Set TAILSCALE_API_KEY, or both TAILSCALE_OAUTH_CLIENT_ID and "
            "TAILSCALE_OAUTH_CLIENT_SECRET.",
            file=sys.stderr,
        )
        return 2

    api = TailscaleAPI(token, timeout=args.timeout)
    if args.profile == "dashboard":
        endpoints = [TAILNET_ENDPOINTS[0]]
    else:
        endpoints = list(TAILNET_ENDPOINTS)
        if args.include_logs:
            endpoints.extend(LOG_ENDPOINTS)

    collected: dict[str, Any] = {}
    errors: dict[str, Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(collect_endpoint, api, endpoint, args.tailnet) for endpoint in endpoints
        ]
        for future in concurrent.futures.as_completed(futures):
            try:
                name, value, error = future.result()
            except APIError as exc:
                print(f"Fatal API error: {exc}", file=sys.stderr)
                return 1
            if error:
                errors[name] = error
            else:
                collected[name] = value

    now = dt.datetime.now(dt.UTC)
    if args.profile == "dashboard":
        try:
            config = load_dashboard_config(args.dashboard_config)
            result = dashboard_inventory(collected.get("devices"), config, args.only_ui)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    else:
        details: dict[str, Any] = {}
        if not args.no_details:
            detail_values, detail_errors = collect_details(
                api, collected, args.tailnet, max(1, args.workers)
            )
            details = nest_details(detail_values)
            errors.update({f"details/{key}": value for key, value in detail_errors.items()})

        result = {
            "metadata": {
                "generated_at": now.isoformat(),
                "tailnet": args.tailnet,
                "api_base": API_BASE,
                "auth_method": auth_method,
                "includes_logs": args.include_logs,
                "includes_details": not args.no_details,
                "collector": "tailscale_api_inventory.py",
            },
            "inventory": collected,
            "details": details,
            "unavailable": errors,
        }
        if not args.no_redact:
            result = redact_secrets(result)

    suffix = "yaml" if args.format == "yaml" else "json"
    output = args.output or inventory_path(
        f"tailscale-api-{args.profile}-{now.strftime('%Y%m%dT%H%M%SZ')}.{suffix}"
    )
    try:
        write_output(result, output, args.format)
    except (OSError, RuntimeError) as exc:
        print(f"Could not write inventory: {exc}", file=sys.stderr)
        return 1

    if args.profile == "dashboard":
        count = len(result["tailnet"]["apps"])
        print(f"Wrote {output} ({count} dashboard apps).")
    else:
        print(f"Wrote {output} ({len(collected)} sections, {len(errors)} unavailable endpoints).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
