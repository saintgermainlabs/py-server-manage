from __future__ import annotations

import json
from pathlib import Path

import yaml

from serverops.tailscale.nodes import parse_nodes, parse_nodes_file, write_nodes


def _sample_inventory() -> dict:
    return {
        "metadata": {
            "generated_at": "2026-07-28T01:00:00+00:00",
            "tailnet": "-",
            "collector": "tailscale_api_inventory.py",
            "api_base": "https://api.tailscale.com/api/v2",
        },
        "inventory": {
            "users": {
                "users": [
                    {
                        "id": "uFakeUser01",
                        "loginName": "alice@example.com",
                        "role": "owner",
                    }
                ]
            },
            "keys": {"keys": [{"id": "kFakeKey01", "keyType": "auth"}]},
            "devices": {
                "devices": [
                    {
                        "id": "111",
                        "nodeId": "nAliceNode",
                        "hostname": "portal",
                        "name": "portal.example.ts.net",
                        "addresses": ["100.64.0.1", "fd7a:115c:a1e0::1"],
                        "os": "linux",
                        "tags": ["tag:portal"],
                        "user": "alice@example.com",
                        "authorized": True,
                        "connectedToControl": True,
                        "machineKey": "mkey:should-not-appear",
                        "nodeKey": "nodekey:should-not-appear",
                        "advertisedRoutes": [],
                        "enabledRoutes": [],
                    },
                    {
                        "id": "222",
                        "nodeId": "nBobNode",
                        "hostname": "vault",
                        "name": "vault.example.ts.net",
                        "addresses": ["100.64.0.2"],
                        "os": "linux",
                        "tags": ["tag:vault"],
                        "user": "bob@example.com",
                        "authorized": True,
                        "connectedToControl": False,
                    },
                ]
            },
        },
        "details": {
            "users": {"uFakeUser01": {"loginName": "alice@example.com"}},
            "devices": {
                "111": {
                    "record": {
                        "id": "111",
                        "hostname": "portal",
                        "user": "alice@example.com",
                    },
                    "routes": {
                        "advertisedRoutes": ["10.0.0.0/24"],
                        "enabledRoutes": ["10.0.0.0/24"],
                    },
                    "posture_attributes": {"attributes": {"node:os": "linux"}},
                }
            },
        },
    }


def test_parse_nodes_keeps_only_devices_and_strips_users() -> None:
    result = parse_nodes(_sample_inventory())

    assert result["node_count"] == 2
    assert "users" not in result
    assert "keys" not in result
    assert [node["hostname"] for node in result["nodes"]] == ["portal", "vault"]

    portal = result["nodes"][0]
    assert portal["addresses"] == ["100.64.0.1", "fd7a:115c:a1e0::1"]
    assert portal["tags"] == ["tag:portal"]
    assert portal["advertisedRoutes"] == ["10.0.0.0/24"]
    assert portal["enabledRoutes"] == ["10.0.0.0/24"]
    assert portal["posture_attributes"] == {"attributes": {"node:os": "linux"}}
    assert "user" not in portal
    assert "machineKey" not in portal
    assert "nodeKey" not in portal

    serialized = yaml.safe_dump(result)
    assert "alice@example.com" not in serialized
    assert "bob@example.com" not in serialized
    assert "uFakeUser01" not in serialized
    assert "mkey:should-not-appear" not in serialized


def test_parse_nodes_file_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "inventory.yaml"
    output = tmp_path / "nodes.yaml"
    source.write_text(yaml.safe_dump(_sample_inventory()), encoding="utf-8")

    nodes = parse_nodes_file(source)
    write_nodes(nodes, output, "yaml")

    loaded = yaml.safe_load(output.read_text(encoding="utf-8"))
    assert loaded["node_count"] == 2
    assert {node["hostname"] for node in loaded["nodes"]} == {"portal", "vault"}


def test_parse_nodes_accepts_json_inventory(tmp_path: Path) -> None:
    source = tmp_path / "inventory.json"
    source.write_text(json.dumps(_sample_inventory()), encoding="utf-8")
    result = parse_nodes_file(source)
    assert result["node_count"] == 2


def test_parse_nodes_empty_devices() -> None:
    result = parse_nodes({"metadata": {}, "inventory": {"devices": {"devices": []}}})
    assert result == {
        "schema_version": 1,
        "source": {
            "generated_at": None,
            "tailnet": None,
            "collector": None,
            "api_base": None,
        },
        "node_count": 0,
        "nodes": [],
    }
