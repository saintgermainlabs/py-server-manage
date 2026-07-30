# ServerOps (`py-server-manage`)

Safe, modular Python toolkit for managing Coolify hosts, Tailscale, diagnostics, and **host-level backups**.

## Priority

Backup and disaster recovery for the Hetzner Coolify server are the primary mission. Inventory/dashboard helpers are useful but secondary.

## Develop locally, back up on the server

| Role | Machine | Responsibility |
|------|---------|----------------|
| Development | Laptop | Code, unit tests, Coolify/Tailscale API tooling |
| Backup runtime | Hetzner Ubuntu | `serverops`, Borg, borgmatic, secrets, systemd |

Do **not** run Borg archives from the laptop against server paths. Deploy this repo to the server with git.

Full install guide: [`docs/backup-installation.md`](docs/backup-installation.md).

## Local install (laptop)

```bash
uv sync --all-extras
```

Private config (optional):

```text
~/.config/py-server-manage/config.yaml
```

See [`config/serverops.example.yaml`](config/serverops.example.yaml) and [`.env.example`](.env.example).

### Secrets via mise (`.env.local`)

[`mise.toml`](mise.toml) loads [`.env`](.env) and [`.env.local`](.env.local) (gitignored) into the environment for every mise task and `mise exec` / `mise run`. Put Vault AppRole credentials there for local inventory encryption:

```bash
# .env.local (never commit)
VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
VAULT_ROLE_ID=...
VAULT_SECRET_ID=...
```

The AppRole SecretID is short-lived and use-limited. When encrypt fails with an
AppRole login error, mint a fresh SecretID (see [`docs/VAULT.md`](docs/VAULT.md))
and update `.env.local`. Unset stale `VAULT_TOKEN` values; an expired token
blocks AppRole unless both are present (token is tried first, then AppRole).

Then:

```bash
mise run cli -- coolify inventory
mise run cli -- tailscale inventory
mise run cli -- inventory encrypt data/inventory/coolify-inventory.yaml
# → data/encrypted/inventory/<basename>.yaml.enc
```

See [`docs/inventory-security.md`](docs/inventory-security.md) and [`docs/VAULT.md`](docs/VAULT.md).

## Server deploy (Hetzner)

```bash
sudo git clone YOUR_GIT_URL /opt/py-server-manage
cd /opt/py-server-manage
sudo uv sync --all-extras
sudo apt-get install -y borgbackup borgmatic
sudo uv run serverops backup generate-config
sudo uv run serverops backup install --dry-run
sudo uv run serverops backup discover
sudo uv run serverops backup preflight
```

## CLI modules

```bash
uv run serverops --help
uv run serverops backup discover
uv run serverops backup generate-config
uv run serverops backup install --dry-run
uv run serverops backup preflight
uv run serverops diagnostics doctor
uv run serverops coolify health
uv run serverops tailscale nodes
```

Compatibility aliases: `doctor`, `host`, `docker`, `debug`.

## Backup discovery

```bash
uv run serverops backup discover
```

Writes under `data/inventory/` and `data/reports/`.

Example settings: [`config/backup.example.yaml`](config/backup.example.yaml).

## Safety

- Diagnostics and `backup discover` / `preflight` are read-only.
- `backup install` defaults to dry-run; `--apply` is required to write live files.
- Never commit secrets, Borg passphrases, or Coolify tokens.

## Tests

```bash
uv run pytest
uv run ruff check .
```
