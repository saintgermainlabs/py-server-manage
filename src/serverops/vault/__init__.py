"""HashiCorp Vault integration (AppRole auth, Transit inventory encryption)."""

from serverops.vault.client import automatic_vault_client, create_vault_client
from serverops.vault.errors import (
    VaultAuthenticationError,
    VaultAuthorizationError,
    VaultError,
)
from serverops.vault.transit import decrypt_inventory, encrypt_inventory

__all__ = [
    "VaultAuthenticationError",
    "VaultAuthorizationError",
    "VaultError",
    "automatic_vault_client",
    "create_vault_client",
    "decrypt_inventory",
    "encrypt_inventory",
]
