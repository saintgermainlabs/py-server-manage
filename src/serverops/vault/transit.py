"""Vault Transit engine helpers for inventory encryption."""

from __future__ import annotations

import base64
import os
from typing import TYPE_CHECKING, Any

from hvac import exceptions as hvac_exceptions

from serverops.vault.errors import (
    VaultError,
    map_transit_error,
    sanitize_error,
)

if TYPE_CHECKING:
    from hvac import Client as HvacClient

DEFAULT_TRANSIT_MOUNT = "transit"
DEFAULT_TRANSIT_KEY = "inventory"


def resolve_transit_mount(mount_point: str | None = None) -> str:
    raw = mount_point or os.environ.get("VAULT_TRANSIT_MOUNT", DEFAULT_TRANSIT_MOUNT)
    return raw.strip() or DEFAULT_TRANSIT_MOUNT


def resolve_transit_key(key_name: str | None = None) -> str:
    raw = key_name or os.environ.get("VAULT_TRANSIT_KEY", DEFAULT_TRANSIT_KEY)
    return raw.strip() or DEFAULT_TRANSIT_KEY


def _client_secrets(client: HvacClient) -> tuple[str | None, ...]:
    token = getattr(client, "token", None)
    return (token,) if token else ()


def encrypt_inventory(
    client: HvacClient,
    data: bytes,
    *,
    mount_point: str | None = None,
    key_name: str | None = None,
) -> str:
    """Encrypt inventory *data* with Vault Transit.

    Mount and key default to ``VAULT_TRANSIT_MOUNT`` / ``VAULT_TRANSIT_KEY`` or
    ``transit`` / ``inventory``.

    Returns the opaque ``vault:v1:…`` ciphertext string.
    """
    mount = resolve_transit_mount(mount_point)
    key = resolve_transit_key(key_name)
    plaintext_b64 = base64.b64encode(data).decode("ascii")
    secrets = _client_secrets(client)
    try:
        result: dict[str, Any] = client.secrets.transit.encrypt_data(
            name=key,
            plaintext=plaintext_b64,
            mount_point=mount,
        )
    except hvac_exceptions.VaultError as exc:
        raise map_transit_error(
            exc,
            mount_point=mount,
            key_name=key,
            operation="encrypt",
            secrets=secrets,
        ) from None

    try:
        return result["data"]["ciphertext"]
    except KeyError as exc:
        raise VaultError(
            sanitize_error(
                f"Unexpected Vault encrypt response: {result!r}",
                *secrets,
            )
        ) from exc


def decrypt_inventory(
    client: HvacClient,
    ciphertext: str,
    *,
    mount_point: str | None = None,
    key_name: str | None = None,
) -> bytes:
    """Decrypt a ciphertext string produced by :func:`encrypt_inventory`."""
    mount = resolve_transit_mount(mount_point)
    key = resolve_transit_key(key_name)
    secrets = _client_secrets(client)
    try:
        result: dict[str, Any] = client.secrets.transit.decrypt_data(
            name=key,
            ciphertext=ciphertext,
            mount_point=mount,
        )
    except hvac_exceptions.VaultError as exc:
        raise map_transit_error(
            exc,
            mount_point=mount,
            key_name=key,
            operation="decrypt",
            secrets=secrets,
        ) from None

    try:
        plaintext_b64 = result["data"]["plaintext"]
        return base64.b64decode(plaintext_b64)
    except (KeyError, ValueError) as exc:
        raise VaultError(
            sanitize_error(
                f"Failed to decode Vault decrypt response: {exc}",
                *secrets,
            )
        ) from exc
