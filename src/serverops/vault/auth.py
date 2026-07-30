"""Vault credential resolution and authentication."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from hvac import exceptions as hvac_exceptions

from serverops.vault.errors import VaultAuthenticationError, VaultError, sanitize_error

if TYPE_CHECKING:
    from hvac import Client as HvacClient

DEFAULT_APPROLE_MOUNT = "approle"


@dataclass(frozen=True)
class AppRoleCredentials:
    role_id: str
    secret_id: str


def read_secret_file(path: str | Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise VaultError(f"Failed to read Vault credential file: {exc}") from exc


def tls_verify() -> bool | str:
    skip = os.environ.get("VAULT_SKIP_VERIFY", "").strip().lower()
    if skip in ("1", "true", "yes"):
        return False
    cacert = os.environ.get("VAULT_CACERT", "").strip()
    if cacert:
        return cacert
    return True


def resolve_vault_token(vault_token: str | None = None) -> str | None:
    return (vault_token or os.environ.get("VAULT_TOKEN", "")).strip() or None


def resolve_approle_credentials(
    role_id: str | None = None,
    secret_id: str | None = None,
    *,
    role_id_file: str | Path | None = None,
    secret_id_file: str | Path | None = None,
) -> AppRoleCredentials | None:
    resolved_role_id = (role_id or os.environ.get("VAULT_ROLE_ID", "")).strip() or None
    resolved_secret_id = (secret_id or os.environ.get("VAULT_SECRET_ID", "")).strip() or None

    rid_file = role_id_file or os.environ.get("VAULT_ROLE_ID_FILE", "").strip() or None
    sid_file = secret_id_file or os.environ.get("VAULT_SECRET_ID_FILE", "").strip() or None

    if not resolved_role_id and rid_file:
        resolved_role_id = read_secret_file(rid_file)
    if not resolved_secret_id and sid_file:
        resolved_secret_id = read_secret_file(sid_file)

    if resolved_role_id and resolved_secret_id:
        return AppRoleCredentials(role_id=resolved_role_id, secret_id=resolved_secret_id)
    return None


def login_approle(
    client: HvacClient,
    role_id: str,
    secret_id: str,
    *,
    mount_point: str = DEFAULT_APPROLE_MOUNT,
) -> None:
    response = client.auth.approle.login(
        role_id=role_id,
        secret_id=secret_id,
        mount_point=mount_point,
    )
    try:
        client.token = response["auth"]["client_token"]
    except (KeyError, TypeError) as exc:
        raise VaultAuthenticationError(
            "AppRole login response did not include auth.client_token."
        ) from exc


def apply_authentication(
    client: HvacClient,
    vault_token: str | None,
    approle: AppRoleCredentials | None,
) -> None:
    secrets_for_sanitize: tuple[str | None, ...] = (
        vault_token,
        approle.role_id if approle else None,
        approle.secret_id if approle else None,
    )

    try:
        if vault_token:
            client.token = vault_token
        elif approle:
            login_approle(client, approle.role_id, approle.secret_id)
        else:
            raise VaultError(
                "Vault credentials required: set VAULT_TOKEN or AppRole "
                "role_id and secret_id (environment, files, or arguments)."
            )
    except hvac_exceptions.VaultError as exc:
        raw = sanitize_error(str(exc), *secrets_for_sanitize)
        lower = raw.lower()
        if (
            approle
            and not vault_token
            and ("permission denied" in lower or "invalid" in lower or "secret" in lower)
        ):
            raise VaultAuthenticationError(
                "AppRole login failed: invalid RoleID/SecretID, expired SecretID, "
                "or SecretID use limit reached (this role allows limited uses). "
                "An administrator must mint a new SecretID "
                "(`vault write -f auth/approle/role/py-server-manage/secret-id`) "
                "and update VAULT_SECRET_ID in .env.local. See docs/VAULT.md."
            ) from None
        raise VaultAuthenticationError(raw) from None
    except OSError as exc:
        raise VaultError(
            sanitize_error(f"Failed to read Vault credential file: {exc}", *secrets_for_sanitize)
        ) from None
