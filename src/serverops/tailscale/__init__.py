"""Tailscale inventory and diagnostics."""

from __future__ import annotations

from .api_inventory import main as api_inventory_main
from .inventory import main as inventory_main
from .nodes import parse_nodes, parse_nodes_file, write_nodes

__all__ = [
    "api_inventory_main",
    "inventory_main",
    "parse_nodes",
    "parse_nodes_file",
    "write_nodes",
]
