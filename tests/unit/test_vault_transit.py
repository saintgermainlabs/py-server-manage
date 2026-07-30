"""Unit tests for serverops.vault (Vault Transit + AppRole auth)."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hvac import exceptions as hvac_exceptions

from serverops.paths import (
    decrypted_inventory_output_path,
    encrypted_inventory_output_path,
)
from serverops.vault import (
    VaultAuthenticationError,
    VaultAuthorizationError,
    VaultError,
    create_vault_client,
    decrypt_inventory,
    encrypt_inventory,
)
from serverops.vault.client import DEFAULT_VAULT_ADDR, automatic_vault_client
from serverops.vault.transit import DEFAULT_TRANSIT_KEY, DEFAULT_TRANSIT_MOUNT

# ---------------------------------------------------------------------------
# Path defaults
# ---------------------------------------------------------------------------


def test_encrypted_inventory_output_path() -> None:
    src = Path("/tmp/data/tailscale-api-nodes.yaml")
    assert encrypted_inventory_output_path(src).name == "tailscale-api-nodes.yaml.enc"
    assert encrypted_inventory_output_path(src).parent.name == "inventory"


def test_decrypted_inventory_output_path() -> None:
    enc = Path("/tmp/data/encrypted/inventory/foo.yaml.enc")
    out = decrypted_inventory_output_path(enc)
    assert out.name == "foo.yaml"
    assert out.parent.name == "inventory"


def test_inventory_path_helper() -> None:
    from serverops.paths import INVENTORY_DIR, inventory_path

    assert inventory_path("coolify-inventory.yaml") == INVENTORY_DIR / "coolify-inventory.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_ADDR = "https://vault.example.com:8200"
FAKE_TOKEN = "s.FAKEVAULTTOKEN"  # obviously fake
FAKE_ROLE_ID = "fake-role-id-00000000"
FAKE_SECRET_ID = "fake-secret-id-00000000"
PLAINTEXT = b"secret inventory data"
CIPHERTEXT = "vault:v1:AAABBBCCC"


def _mock_hvac_client(*, authenticated: bool = True) -> MagicMock:
    client = MagicMock()
    client.is_authenticated.return_value = authenticated
    client.token = FAKE_TOKEN
    client.auth.approle.login.return_value = {"auth": {"client_token": FAKE_TOKEN}}
    client.secrets.transit.encrypt_data.return_value = {"data": {"ciphertext": CIPHERTEXT}}
    plaintext_b64 = base64.b64encode(PLAINTEXT).decode()
    client.secrets.transit.decrypt_data.return_value = {"data": {"plaintext": plaintext_b64}}
    return client


# ---------------------------------------------------------------------------
# create_vault_client
# ---------------------------------------------------------------------------


class TestCreateVaultClient:
    def test_token_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client()
            mock_client_cls.return_value = mock_client

            client = create_vault_client(vault_token=FAKE_TOKEN)

        assert client is mock_client
        mock_client_cls.assert_called_once()
        assert mock_client.token == FAKE_TOKEN
        mock_client.auth.approle.login.assert_not_called()
        mock_client.is_authenticated.assert_called_once()

    def test_token_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.setenv("VAULT_TOKEN", FAKE_TOKEN)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client()
            mock_client_cls.return_value = mock_client

            create_vault_client()

        assert mock_client.token == FAKE_TOKEN
        mock_client.auth.approle.login.assert_not_called()

    def test_approle_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client()
            mock_client_cls.return_value = mock_client

            client = create_vault_client(
                role_id=FAKE_ROLE_ID,
                secret_id=FAKE_SECRET_ID,
            )

        assert client is mock_client
        mock_client.auth.approle.login.assert_called_once_with(
            role_id=FAKE_ROLE_ID,
            secret_id=FAKE_SECRET_ID,
            mount_point="approle",
        )
        assert mock_client.token == FAKE_TOKEN
        mock_client.is_authenticated.assert_called_once()

    def test_approle_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.setenv("VAULT_ROLE_ID", FAKE_ROLE_ID)
        monkeypatch.setenv("VAULT_SECRET_ID", FAKE_SECRET_ID)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client()
            mock_client_cls.return_value = mock_client

            create_vault_client()

        mock_client.auth.approle.login.assert_called_once_with(
            role_id=FAKE_ROLE_ID,
            secret_id=FAKE_SECRET_ID,
            mount_point="approle",
        )

    def test_default_addr_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VAULT_ADDR", raising=False)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client()
            mock_client_cls.return_value = mock_client

            create_vault_client(vault_token=FAKE_TOKEN)

        mock_client_cls.assert_called_once()
        assert mock_client_cls.call_args.kwargs["url"] == DEFAULT_VAULT_ADDR

    def test_missing_credentials_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)
        monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
        monkeypatch.delenv("VAULT_SECRET_ID", raising=False)

        with pytest.raises(VaultError, match="credentials"):
            create_vault_client()

    def test_not_authenticated_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.delenv("VAULT_ROLE_ID", raising=False)
        monkeypatch.delenv("VAULT_SECRET_ID", raising=False)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client(authenticated=False)
            mock_client_cls.return_value = mock_client

            with pytest.raises(VaultAuthenticationError, match="invalid or expired"):
                create_vault_client(vault_token=FAKE_TOKEN)

    def test_expired_token_falls_back_to_approle(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)
        monkeypatch.delenv("VAULT_TOKEN", raising=False)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client(authenticated=False)
            # Token check fails; AppRole login then succeeds.
            mock_client.is_authenticated.side_effect = [False, True]
            mock_client_cls.return_value = mock_client

            client = create_vault_client(
                vault_token=FAKE_TOKEN,
                role_id=FAKE_ROLE_ID,
                secret_id=FAKE_SECRET_ID,
            )

        assert client is mock_client
        mock_client.auth.approle.login.assert_called_once()

    def test_approle_login_error_redacts_secrets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.auth.approle.login.side_effect = hvac_exceptions.Forbidden(
                f"invalid secret {FAKE_SECRET_ID}",
                method="post",
                url=f"{FAKE_ADDR}/v1/auth/approle/login",
            )
            mock_client_cls.return_value = mock_client

            with pytest.raises(VaultAuthenticationError) as exc_info:
                create_vault_client(role_id=FAKE_ROLE_ID, secret_id=FAKE_SECRET_ID)

        assert FAKE_SECRET_ID not in str(exc_info.value)
        assert FAKE_ROLE_ID not in str(exc_info.value)
        assert "SecretID" in str(exc_info.value)

    def test_automatic_vault_client_alias(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = _mock_hvac_client()
            mock_client_cls.return_value = mock_client

            client = automatic_vault_client(vault_token=FAKE_TOKEN)

        assert client is mock_client

    def test_approle_missing_client_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_ADDR", FAKE_ADDR)

        with patch("serverops.vault.client.hvac.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.auth.approle.login.return_value = {"auth": {}}
            mock_client_cls.return_value = mock_client

            with pytest.raises(VaultAuthenticationError, match="client_token"):
                create_vault_client(role_id=FAKE_ROLE_ID, secret_id=FAKE_SECRET_ID)


# ---------------------------------------------------------------------------
# encrypt_inventory / decrypt_inventory
# ---------------------------------------------------------------------------


class TestEncryptInventory:
    def test_success(self) -> None:
        client = _mock_hvac_client()
        result = encrypt_inventory(client, PLAINTEXT)

        assert result == CIPHERTEXT
        plaintext_b64 = base64.b64encode(PLAINTEXT).decode()
        client.secrets.transit.encrypt_data.assert_called_once_with(
            name=DEFAULT_TRANSIT_KEY,
            plaintext=plaintext_b64,
            mount_point=DEFAULT_TRANSIT_MOUNT,
        )

    def test_custom_mount_and_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VAULT_TRANSIT_MOUNT", "custom-transit")
        monkeypatch.setenv("VAULT_TRANSIT_KEY", "custom-key")
        client = _mock_hvac_client()
        encrypt_inventory(client, PLAINTEXT)
        client.secrets.transit.encrypt_data.assert_called_once_with(
            name="custom-key",
            plaintext=base64.b64encode(PLAINTEXT).decode("ascii"),
            mount_point="custom-transit",
        )

    def test_encrypt_decrypt_round_trip(self) -> None:
        client = _mock_hvac_client()
        ciphertext = encrypt_inventory(client, PLAINTEXT)
        assert decrypt_inventory(client, ciphertext) == PLAINTEXT

    def test_forbidden_maps_to_authorization_error(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.encrypt_data.side_effect = hvac_exceptions.Forbidden(
            "permission denied",
            method="post",
            url=f"{FAKE_ADDR}/v1/transit/encrypt/{DEFAULT_TRANSIT_KEY}",
        )

        with pytest.raises(VaultAuthorizationError) as exc_info:
            encrypt_inventory(client, PLAINTEXT)

        msg = str(exc_info.value)
        assert "transit/encrypt/inventory" in msg
        assert "py-server-manage" in msg
        assert "update" in msg
        assert FAKE_TOKEN not in msg

    def test_vault_down_maps_to_vault_error(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.encrypt_data.side_effect = hvac_exceptions.VaultDown(
            "connection refused",
            method="post",
            url=f"{FAKE_ADDR}/v1/transit/encrypt/{DEFAULT_TRANSIT_KEY}",
        )

        with pytest.raises(VaultError, match="unavailable"):
            encrypt_inventory(client, PLAINTEXT)

    def test_token_not_in_exception(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.encrypt_data.side_effect = hvac_exceptions.Forbidden(
            f"denied with token {FAKE_TOKEN}",
            method="post",
            url=f"{FAKE_ADDR}/v1/transit/encrypt/{DEFAULT_TRANSIT_KEY}",
        )

        with pytest.raises(VaultAuthorizationError) as exc_info:
            encrypt_inventory(client, PLAINTEXT)

        assert FAKE_TOKEN not in str(exc_info.value)

    def test_missing_data_key_raises_vault_error(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.encrypt_data.return_value = {"lease_id": ""}

        with pytest.raises(VaultError):
            encrypt_inventory(client, PLAINTEXT)


class TestDecryptInventory:
    def test_success(self) -> None:
        client = _mock_hvac_client()
        result = decrypt_inventory(client, CIPHERTEXT)

        assert result == PLAINTEXT
        client.secrets.transit.decrypt_data.assert_called_once_with(
            name=DEFAULT_TRANSIT_KEY,
            ciphertext=CIPHERTEXT,
            mount_point=DEFAULT_TRANSIT_MOUNT,
        )

    def test_token_not_in_exception(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.decrypt_data.side_effect = hvac_exceptions.InvalidRequest(
            "invalid ciphertext",
            method="post",
            url=f"{FAKE_ADDR}/v1/transit/decrypt/{DEFAULT_TRANSIT_KEY}",
        )

        with pytest.raises(VaultError) as exc_info:
            decrypt_inventory(client, CIPHERTEXT)

        assert FAKE_TOKEN not in str(exc_info.value)

    def test_malformed_base64_raises_vault_error(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.decrypt_data.return_value = {
            "data": {"plaintext": "NOT_VALID_BASE64!!!"},
        }

        with pytest.raises(VaultError):
            decrypt_inventory(client, CIPHERTEXT)

    def test_missing_plaintext_key_raises_vault_error(self) -> None:
        client = _mock_hvac_client()
        client.secrets.transit.decrypt_data.return_value = {"data": {}}

        with pytest.raises(VaultError):
            decrypt_inventory(client, CIPHERTEXT)


def test_fake_token_value_obviously_fake() -> None:
    assert FAKE_TOKEN.startswith("s.FAKE"), "Test token must be obviously fake."


# ---------------------------------------------------------------------------
# CLI subcommand integration (no live Vault)
# ---------------------------------------------------------------------------


def test_encrypt_cli_missing_file(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from serverops.inventory.cli import app

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "encrypt",
            str(tmp_path / "nonexistent.yaml"),
            "--vault-addr",
            FAKE_ADDR,
            "--vault-token",
            FAKE_TOKEN,
        ],
    )
    assert result.exit_code != 0
    assert "not found" in result.output


def test_encrypt_cli_writes_enc_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from serverops import paths
    from serverops.inventory.cli import app

    enc_dir = tmp_path / "encrypted" / "inventory"
    monkeypatch.setattr(paths, "ENCRYPTED_INVENTORY_DIR", enc_dir)

    src = tmp_path / "inventory.yaml"
    src.write_bytes(PLAINTEXT)

    mock_client = _mock_hvac_client()
    runner = CliRunner()
    with patch("serverops.inventory.cli.create_vault_client", return_value=mock_client):
        result = runner.invoke(
            app,
            ["encrypt", str(src), "--vault-addr", FAKE_ADDR, "--vault-token", FAKE_TOKEN],
        )

    assert result.exit_code == 0, result.output
    enc_file = enc_dir / "inventory.yaml.enc"
    assert enc_file.exists()
    assert enc_file.read_text(encoding="utf-8").strip() == CIPHERTEXT
    assert FAKE_TOKEN not in enc_file.read_text(encoding="utf-8")


def test_decrypt_cli_writes_original_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from serverops import paths
    from serverops.inventory.cli import app

    inv_dir = tmp_path / "inventory"
    monkeypatch.setattr(paths, "INVENTORY_DIR", inv_dir)

    enc = tmp_path / "inventory.yaml.enc"
    enc.write_text(CIPHERTEXT + "\n", encoding="utf-8")

    mock_client = _mock_hvac_client()
    runner = CliRunner()
    with patch("serverops.inventory.cli.create_vault_client", return_value=mock_client):
        result = runner.invoke(
            app,
            ["decrypt", str(enc), "--vault-addr", FAKE_ADDR, "--vault-token", FAKE_TOKEN],
        )

    assert result.exit_code == 0, result.output
    out_file = inv_dir / "inventory.yaml"
    assert out_file.exists()
    assert out_file.read_bytes() == PLAINTEXT


def test_decrypt_cli_token_not_in_output(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from serverops.inventory.cli import app

    enc = tmp_path / "inventory.yaml.enc"
    enc.write_text(CIPHERTEXT + "\n", encoding="utf-8")

    mock_client = _mock_hvac_client()
    mock_client.secrets.transit.decrypt_data.side_effect = hvac_exceptions.Forbidden(
        "permission denied",
        method="post",
        url=f"{FAKE_ADDR}/v1/transit/decrypt/{DEFAULT_TRANSIT_KEY}",
    )

    runner = CliRunner()
    with patch("serverops.inventory.cli.create_vault_client", return_value=mock_client):
        result = runner.invoke(
            app,
            ["decrypt", str(enc), "--vault-addr", FAKE_ADDR, "--vault-token", FAKE_TOKEN],
        )

    assert result.exit_code != 0
    assert FAKE_TOKEN not in (result.output or "")


def test_encrypt_cli_approle_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from serverops import paths
    from serverops.inventory.cli import app

    enc_dir = tmp_path / "encrypted" / "inventory"
    monkeypatch.setattr(paths, "ENCRYPTED_INVENTORY_DIR", enc_dir)

    src = tmp_path / "inventory.yaml"
    src.write_bytes(PLAINTEXT)
    mock_client = _mock_hvac_client()

    runner = CliRunner()
    with patch(
        "serverops.inventory.cli.create_vault_client", return_value=mock_client
    ) as mock_create:
        result = runner.invoke(
            app,
            [
                "encrypt",
                str(src),
                "--vault-addr",
                FAKE_ADDR,
                "--vault-role-id",
                FAKE_ROLE_ID,
                "--vault-secret-id",
                FAKE_SECRET_ID,
            ],
        )

    assert result.exit_code == 0, result.output
    mock_create.assert_called_once()
    call_kw = mock_create.call_args.kwargs
    assert call_kw["role_id"] == FAKE_ROLE_ID
    assert call_kw["secret_id"] == FAKE_SECRET_ID
