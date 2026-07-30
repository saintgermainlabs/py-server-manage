"""Authenticated HashiCorp Vault client factory."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import hvac

from serverops.vault.auth import (
    apply_authentication,
    resolve_approle_credentials,
    resolve_vault_token,
    tls_verify,
)
from serverops.vault.errors import VaultAuthenticationError, VaultError

if TYPE_CHECKING:
    from hvac import Client as HvacClient

DEFAULT_VAULT_ADDR = "https://vault.tiger-bushmaster.ts.net"


def create_vault_client(
    *,
    vault_addr: str | None = None,
    vault_token: str | None = None,
    role_id: str | None = None,
    secret_id: str | None = None,
    role_id_file: str | Path | None = None,
    secret_id_file: str | Path | None = None,
) -> HvacClient:
    """Build an authenticated ``hvac`` client.

    Precedence for the Vault address: ``vault_addr`` argument, then ``VAULT_ADDR``,
    then :data:`DEFAULT_VAULT_ADDR`.

    Authentication:
    1. ``vault_token`` or ``VAULT_TOKEN``
    2. Else AppRole via ``role_id``/``secret_id`` (args or env), or credential files.

    TLS: ``VAULT_CACERT``, ``VAULT_SKIP_VERIFY``.
    """
    addr = (vault_addr or os.environ.get("VAULT_ADDR", DEFAULT_VAULT_ADDR)).strip()
    if not addr:
        raise VaultError("Vault address is required (VAULT_ADDR or vault_addr).")

    token = resolve_vault_token(vault_token)
    approle = resolve_approle_credentials(
        role_id,
        secret_id,
        role_id_file=role_id_file,
        secret_id_file=secret_id_file,
    )

    client = hvac.Client(url=addr, verify=tls_verify())

    # Prefer an explicit token when it validates. Fall back to AppRole when the
    # token is missing or expired so a stale VAULT_TOKEN / ~/.vault-token does
    # not block automation that still has a valid SecretID.
    if token:
        client.token = token
        if client.is_authenticated():
            return client
        if not approle:
            raise VaultAuthenticationError(
                "Vault token is invalid or expired. Provide a fresh VAULT_TOKEN "
                "or AppRole credentials (VAULT_ROLE_ID / VAULT_SECRET_ID)."
            )

    if approle:
        apply_authentication(client, None, approle)
    else:
        apply_authentication(client, token, approle)

    if not client.is_authenticated():
        raise VaultAuthenticationError("Vault authentication failed.")

    return client


def automatic_vault_client(
    *,
    vault_addr: str | None = None,
    vault_token: str | None = None,
    role_id: str | None = None,
    secret_id: str | None = None,
    role_id_file: str | Path | None = None,
    secret_id_file: str | Path | None = None,
) -> HvacClient:
    """Alias for :func:`create_vault_client` (backward compatibility)."""
    return create_vault_client(
        vault_addr=vault_addr,
        vault_token=vault_token,
        role_id=role_id,
        secret_id=secret_id,
        role_id_file=role_id_file,
        secret_id_file=secret_id_file,
    )
