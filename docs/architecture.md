# Architecture

ServerOps is a Typer CLI that composes feature packages under `src/serverops/`:

| Package | Role |
|---------|------|
| `backup/` | Host-level backup discovery (Phase 1–2); Borg/systemd later |
| `inventory/` | Discovery adapters (`coolify`, `docker`, `system`) + dashboard transforms |
| `coolify/` | Coolify API client and inventory export |
| `tailscale/` | Tailscale CLI/API inventories |
| `diagnostics/` | Host/Docker doctor checks (`debug` alias retained) |
| `openclaw/` | Skill path helpers |
| `vault/` | HashiCorp Vault client (AppRole auth), Transit inventory encrypt/decrypt |
| `utils/` | Redaction, filesystem probes, command wrappers |
| `models/` | Shared Pydantic types |
| `provision/` | Stubs for future host bootstrap |

### `vault/` layout

| Module | Role |
|--------|------|
| `errors.py` | `VaultError`, credential redaction in error messages |
| `auth.py` | Token/AppRole resolution, AppRole login, TLS env handling |
| `client.py` | `create_vault_client()` factory (`automatic_vault_client` alias) |
| `transit.py` | `encrypt_inventory` / `decrypt_inventory` (Transit key `inventory`) |

Shared runners and config live at the package root (`runner.py`, `config.py`, `paths.py`, `app_state.py`).

Generated artifacts go under `data/` (`inventory/`, `reports/`, `backups/`, `restore-tests/`, `transformed/`).
