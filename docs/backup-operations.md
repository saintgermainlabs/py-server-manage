# Backup operations

## Discover (laptop or server)

```bash
uv run serverops backup discover
# Focused database dry-run (no dumps executed):
uv run serverops backup discover-databases
# On the server:
./scripts/backup/discover-databases.sh
```

Review:

- `data/inventory/backup-inventory.yaml`
- `data/reports/backup-inventory.md`
- `data/inventory/system-state.yaml`
- `data/reports/system-state.md`

`discover-databases` prints a dry-run plan of probable DB containers and
proposed methods (`native-dump` vs Redis durability review). It also reconciles
against the allowlist when present (`/etc/server-backup/databases.yaml` or
`config/databases.example.yaml`). It does **not** run `pg_dump` / `mysqldump` /
`mongodump` yet.

### Database allowlist + Vault Transit / Agent

Native dumps will use an explicit allowlist, not auto-discovery alone.

**Recommended laptop workflow**

```bash
# 1. Decrypt inventories (needs Vault decrypt capability)
mise run cli -- inventory decrypt data/encrypted/inventory/coolify-inventory.yaml.enc
# optional if you have a fresh host discover:
mise run cli -- inventory decrypt data/encrypted/inventory/backup-inventory.yaml.enc

# 2. Build allowlist with KV placeholders (dry-run, then apply)
mise run cli -- backup build-databases-allowlist --dry-run
mise run cli -- backup build-databases-allowlist --apply
# → data/inventory/databases.yaml

# 3. (Later) put real DB passwords in Vault KV under
#    secret/data/py-server-manage/backup/databases/<id>
#    or keep placeholders and inject at dump time.

# 4. Encrypt allowlist for git (Transit — same as inventories)
mise run cli -- backup encrypt-databases
# → data/encrypted/inventory/databases.yaml.enc
```

| File | Role |
|---|---|
| `config/databases.example.yaml` | Committed shape + placeholders |
| `data/inventory/databases.yaml` | Generated plaintext (gitignored) |
| `data/encrypted/inventory/databases.yaml.enc` | Transit ciphertext (safe to commit) |
| `deploy/vault-agent/templates/databases.yaml.ctmpl` | Optional Agent render of live `/etc/...` |
| `/etc/server-backup/databases.yaml` | Server runtime allowlist (`0600`) |

See `deploy/vault-agent/README.md`. Store per-DB secrets under
`secret/data/py-server-manage/backup/databases/<id>` (`username`, `password`,
`database`).

On the Hetzner host, prefer running discover after deploy so mandatory paths exist.

## Install / preflight / init / run (server)

Full procedure: [backup-installation.md](backup-installation.md).

Short path (after packages, configs, Storage Box key, and root app config):

```bash
cd ~/py-server-manage   # or /opt/py-server-manage

sudo /home/dom/.local/bin/uv run serverops backup preflight \
  --config /etc/server-backup/backup.yaml --require-credentials

sudo /home/dom/.local/bin/uv run serverops backup init \
  --config /etc/server-backup/backup.yaml --apply

sudo /home/dom/.local/bin/uv run serverops backup list \
  --config /etc/server-backup/backup.yaml

sudo /home/dom/.local/bin/uv run serverops backup run \
  --config /etc/server-backup/backup.yaml --dry-run

sudo /home/dom/.local/bin/uv run serverops backup run \
  --config /etc/server-backup/backup.yaml --apply
```

Notes:

- `init` / `run` default to dry-run; `--apply` is required to mutate.
- Root needs `allow_mutations: true` in `/root/.config/py-server-manage/config.yaml`.
- Keep `/etc/server-backup/backup.yaml` and `/etc/borgmatic/config.yaml` repository
  URLs identical and free of `STORAGE_*` placeholders.
- Current `run` is **files-only** (`databases: []`); dump pipelines are not wired yet.

## Check

```bash
sudo /home/dom/.local/bin/uv run serverops backup check \
  --config /etc/server-backup/backup.yaml
```

## Later / not ready

`restore`, `restore-test`, `status`, and `report` remain stubbed until restore
workflows land. Do not enable systemd backup timers until at least one
successful `backup run --apply`.
