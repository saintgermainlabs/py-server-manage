# Backup installation (remote Hetzner host)

BorgBackup **must** run on the Coolify server, not on a developer laptop.
Develop on your laptop, push to git, then deploy and operate backups on the server.

## Architecture

```text
Laptop (dev)  →  git push  →  Git remote
                                  ↓
                         Hetzner Ubuntu host
                    /opt/py-server-manage (preferred)
                    or ~/py-server-manage
                    serverops + borg + borgmatic
                    systemd timers (enable only after first good run)
                                  ↓
                         Hetzner Storage Box :23
                         ssh://USER@HOST:23/./borg/server-primary
```

**Live runtime (what is enabled today):** [backup-live.md](backup-live.md).

**Repository** here means the encrypted Borg store on the Storage Box — not a git
repo.

## Deploy the repo on the server

Preferred (root-owned install root):

```bash
sudo mkdir -p /opt
sudo git clone https://github.com/saintgermainlabs/py-server-manage.git /opt/py-server-manage
cd /opt/py-server-manage
sudo uv sync --all-extras
```

If passwordless `/opt` install is unavailable, a user clone works for bring-up:

```bash
git clone https://github.com/saintgermainlabs/py-server-manage.git ~/py-server-manage
cd ~/py-server-manage
uv sync --all-extras
```

Later updates:

```bash
cd /opt/py-server-manage   # or ~/py-server-manage
git pull                   # use sudo if the tree is root-owned
uv sync --all-extras
```

### `uv` under sudo

`uv` is often installed only for the login user (`~/.local/bin/uv`). Plain
`sudo uv` fails with `command not found`. Use:

```bash
sudo /home/dom/.local/bin/uv run serverops …
# or
sudo env "PATH=$PATH" uv run serverops …
```

### App config for mutating backup commands

`sudo` loads config from **root’s** home, not `dom`’s:

```bash
sudo mkdir -p /root/.config/py-server-manage
sudo tee /root/.config/py-server-manage/config.yaml >/dev/null <<'EOF'
allow_mutations: true
command_timeout_seconds: 300
EOF
```

Without `allow_mutations: true`, `backup init --apply` and `backup run --apply`
refuse to run. Raise `command_timeout_seconds` for Storage Box latency (default
`20` is often too short).

## System packages

```bash
sudo apt-get update
sudo apt-get install -y borgbackup borgmatic
# Optional DB clients when dump pipelines exist:
# postgresql-client default-mysql-client mongodb-database-tools
```

## Generate staged configs (safe)

```bash
cd ~/py-server-manage   # or /opt/py-server-manage
sudo /home/dom/.local/bin/uv run serverops backup generate-config
```

Writes under `data/backups/generated/`:

- `borgmatic.yaml`
- `credentials.env.example`
- `server-backup.service` / `.timer`
- `server-backup-check.service` / `.timer`
- `backup.yaml`

Review those files. Fill Storage Box placeholders **only** in server-local
`/etc/…` copies after install — never commit real values.

## Preview install (default dry-run)

```bash
sudo /home/dom/.local/bin/uv run serverops backup install --dry-run
sudo /home/dom/.local/bin/uv run serverops backup install --apply
```

Live locations (created on apply):

```text
/etc/server-backup/backup.yaml
/etc/server-backup/credentials.env   # from .example; you must edit secrets
/etc/borgmatic/config.yaml
/var/lib/server-backup/staging
/var/lib/server-backup/restore
/root/.ssh/server-backup-storagebox  # generate/authorize yourself
```

Permissions for secrets: `root:root` and `0600`.

## Storage Box (server only — never commit)

### SSH key and connectivity

1. Create a Storage Box **sub-account** in Hetzner Robot/Cloud (optional but
   recommended).
2. On the server, generate a dedicated key if needed:

```bash
sudo ssh-keygen -t ed25519 -f /root/.ssh/server-backup-storagebox -N ""
```

3. Authorize the **public** key for the Storage Box account.
4. Test (port **23**, not 22):

```bash
sudo ssh -p 23 -i /root/.ssh/server-backup-storagebox \
  -o BatchMode=yes -o ConnectTimeout=10 \
  YOUR_USER@YOUR_HOST.your-storagebox.de exit
echo $?   # expect 0
```

### Parent directory on the box

Borg does **not** create missing parent directories. For
`…/./borg/server-primary`, create `borg` first; `borg init` creates
`server-primary`:

```bash
sudo ssh -p 23 -i /root/.ssh/server-backup-storagebox \
  YOUR_USER@YOUR_HOST.your-storagebox.de mkdir borg
```

If `mkdir` over SSH is denied, create `borg` via SFTP / Robot UI.

### Edit live configs

Edit `/etc/server-backup/backup.yaml` (`sudoedit`):

```yaml
repository:
  url: ssh://uXXXXX@uXXXXX.your-storagebox.de:23/./borg/server-primary
  ssh_key: /root/.ssh/server-backup-storagebox
```

Put the Borg passphrase in Vault KV (`secret/py-server-manage/backup/borg`,
field `passphrase`) and keep a local fallback in
`/etc/server-backup/credentials.env` (`0600`) until Vault Agent is rendering
`/etc/server-backup/borg-passphrase`. See [deploy/vault/README.md](../deploy/vault/README.md).

Also keep a human recovery copy in a password manager. Losing every copy means
backups cannot be restored.

### Keep borgmatic in sync

`backup init` uses `backup.yaml`. `backup list` / `run` use
`/etc/borgmatic/config.yaml`. Both must have the **same real** repository URL.
After editing `backup.yaml`, sync:

```bash
sudo python3 - <<'PY'
from pathlib import Path
import yaml

backup = yaml.safe_load(Path("/etc/server-backup/backup.yaml").read_text())
url = backup["repository"]["url"]
if "STORAGE_HOST" in url or "STORAGE_USER" in url:
    raise SystemExit("backup.yaml still has placeholders")

path = Path("/etc/borgmatic/config.yaml")
cfg = yaml.safe_load(path.read_text())
cfg["repositories"][0]["path"] = url
path.write_text(yaml.safe_dump(cfg, sort_keys=False))
print("Updated /etc/borgmatic/config.yaml")
PY
```

## Preflight → init → first run

```bash
cd ~/py-server-manage   # or /opt/py-server-manage

sudo /home/dom/.local/bin/uv run serverops backup preflight \
  --config /etc/server-backup/backup.yaml \
  --require-credentials

sudo /home/dom/.local/bin/uv run serverops backup init \
  --config /etc/server-backup/backup.yaml --dry-run

sudo /home/dom/.local/bin/uv run serverops backup init \
  --config /etc/server-backup/backup.yaml --apply

sudo /home/dom/.local/bin/uv run serverops backup list \
  --config /etc/server-backup/backup.yaml

sudo /home/dom/.local/bin/uv run serverops backup run \
  --config /etc/server-backup/backup.yaml --dry-run

sudo /home/dom/.local/bin/uv run serverops backup run \
  --config /etc/server-backup/backup.yaml --apply
```

Do **not** enable `server-backup.timer` until a real `--apply` run succeeds.

### Enable timers (after a successful apply)

Installed units from `backup install` default to `/opt/py-server-manage`. If the
repo lives under `/home/dom/py-server-manage`, rewrite the services first so they
use that path **and** pass `--config /etc/server-backup/backup.yaml` (otherwise
the example placeholders are used).

Corrected unit templates are under `data/backups/generated/` after bring-up fixes.
Install and enable:

```bash
cd ~/py-server-manage
sudo cp data/backups/generated/server-backup.service \
        data/backups/generated/server-backup-check.service \
        /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now server-backup.timer
sudo systemctl enable --now server-backup-check.timer
sudo systemctl list-timers 'server-backup*'
sudo systemctl status server-backup.timer server-backup-check.timer --no-pager
```

Optional one-shot smoke test without waiting for the calendar:

```bash
sudo systemctl start server-backup.service
sudo journalctl -u server-backup.service -n 50 --no-pager
```

## Failure playbook

| Symptom | Likely cause | Fix |
|---|---|---|
| `sudo: uv: command not found` | User-local uv not on root PATH | Full path to `~/.local/bin/uv` |
| `allow_mutations: false` | Root app config missing | `/root/.config/py-server-manage/config.yaml` |
| `Could not resolve hostname storage_host` | Placeholder left in borgmatic | Sync URL from `backup.yaml` |
| `Permission denied` on `/etc/…` | Ran install without sudo | Re-run with sudo |
| SSH to Storage Box fails | Wrong key/user/port | Test with `-p 23` and the dedicated key |
| `borg init` fails missing parent | No `borg/` on the box | `mkdir borg` on the Storage Box |
| Timeout during init/run | Default 20s too short | `command_timeout_seconds: 300` under root config |
| `printenv BORG_PASSPHRASE` fails under `borgmatic.service` | Distro unit does not load `credentials.env` | Drop-in `/etc/systemd/system/borgmatic.service.d/credentials.conf` with `EnvironmentFile=-/etc/server-backup/credentials.env`, then `daemon-reload` |
| Vault sealed / 503 on `vault.tiger-bushmaster.ts.net` | Raft sealed (3-of-5 Shamir) | Unseal from a local terminal (`vault operator unseal` ×3). Do not paste unseal keys into chat. Keep `credentials.env` until Agent has rendered `/etc/server-backup/borg-passphrase`. |

## Not yet automated

- Enabling systemd timers with production credentials
- Database dump pipeline (files-only backups today)
- Canonical move of a home clone into `/opt/py-server-manage`

See [backup-operations.md](backup-operations.md) and
[AGENT-BACKUP-IMPLEMENTATION-PLAN.md](../AGENT-BACKUP-IMPLEMENTATION-PLAN.md).
