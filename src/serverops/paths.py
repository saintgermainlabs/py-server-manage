"""Shared filesystem locations for generated artifacts."""

from __future__ import annotations

from pathlib import Path

# src/serverops/paths.py -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
INVENTORY_DIR = DATA_DIR / "inventory"
ENCRYPTED_INVENTORY_DIR = DATA_DIR / "encrypted" / "inventory"
REPORTS_DIR = DATA_DIR / "reports"
BACKUPS_DIR = DATA_DIR / "backups"
RESTORE_TESTS_DIR = DATA_DIR / "restore-tests"

DEFAULT_DATABASES_ALLOWLIST = INVENTORY_DIR / "databases.yaml"
DEFAULT_DATABASES_ALLOWLIST_ENC = ENCRYPTED_INVENTORY_DIR / "databases.yaml.enc"


def encrypted_inventory_output_path(source: Path) -> Path:
    """Default ciphertext path for ``inventory encrypt``."""
    name = source.name
    enc_name = name if name.endswith(".enc") else f"{name}.enc"
    return ENCRYPTED_INVENTORY_DIR / enc_name


def decrypted_inventory_output_path(enc_path: Path) -> Path:
    """Default plaintext path for ``inventory decrypt``."""
    name = enc_path.name
    plain_name = name[:-4] if name.endswith(".enc") else f"{enc_path.stem}.dec"
    return INVENTORY_DIR / plain_name


def data_path(*parts: str) -> Path:
    """Return a path under ``data/`` in the repository root."""
    return DATA_DIR.joinpath(*parts)


def inventory_path(*parts: str) -> Path:
    """Return a path under ``data/inventory/`` for plaintext inventory outputs."""
    return INVENTORY_DIR.joinpath(*parts)
