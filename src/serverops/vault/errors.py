"""Vault error types and credential redaction."""

from __future__ import annotations

from typing import Literal

from hvac import exceptions as hvac_exceptions

TransitOperation = Literal["encrypt", "decrypt"]

# AppRole and ACL policy names for this project (server configuration).
APP_ROLE_NAME = "py-server-manage"
APP_POLICY_NAME = "py-server-manage"


class VaultError(RuntimeError):
    """Raised when Vault authentication or API calls fail."""


class VaultAuthenticationError(VaultError):
    """Vault rejected credentials or the session is not authenticated."""


class VaultAuthorizationError(VaultError):
    """Vault accepted the token but denied the requested path (ACL)."""


def sanitize_error(message: str, *secrets: str | None) -> str:
    """Remove credential substrings from an error message."""
    result = message
    for secret in secrets:
        if secret and len(secret) >= 4:
            result = result.replace(secret, "[REDACTED]")
    return result


def transit_api_path(mount_point: str, operation: TransitOperation, key_name: str) -> str:
    return f"{mount_point}/{operation}/{key_name}"


def authorization_denied_message(
    vault_path: str,
    *,
    operation: TransitOperation,
    capability: str = "update",
    policy_name: str = APP_POLICY_NAME,
    approle_name: str = APP_ROLE_NAME,
) -> str:
    return (
        f"Vault denied {vault_path}. "
        f"AppRole authentication for '{approle_name}' may have succeeded, but the "
        f"token requires '{capability}' capability on that path from the "
        f"'{policy_name}' ACL policy. "
        f"An administrator must repair the server-side policy (see docs/VAULT.md). "
        f"Transit {operation} was not performed."
    )


def map_transit_error(
    exc: BaseException,
    *,
    mount_point: str,
    key_name: str,
    operation: TransitOperation,
    secrets: tuple[str | None, ...] = (),
) -> VaultError:
    """Map hvac Transit failures to project errors with safe messages."""
    path = transit_api_path(mount_point, operation, key_name)

    if isinstance(exc, hvac_exceptions.Forbidden):
        return VaultAuthorizationError(
            sanitize_error(
                authorization_denied_message(path, operation=operation),
                *secrets,
            )
        )

    if isinstance(exc, hvac_exceptions.Unauthorized):
        return VaultAuthenticationError(
            sanitize_error(
                f"Vault rejected the session while calling {path}. "
                "Provide a valid VAULT_TOKEN or AppRole credentials.",
                *secrets,
            )
        )

    if isinstance(exc, (hvac_exceptions.VaultDown, hvac_exceptions.BadGateway)):
        return VaultError(
            sanitize_error(
                f"Vault is unavailable for {path}: {exc}",
                *secrets,
            )
        )

    if isinstance(exc, hvac_exceptions.VaultError):
        return VaultError(sanitize_error(str(exc), *secrets))

    return VaultError(sanitize_error(f"Unexpected Vault error for {path}: {exc}", *secrets))
