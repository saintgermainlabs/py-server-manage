---
name: backup-install
description: >-
  Install and initialize Borg/borgmatic backups on the Hetzner Coolify host with
  a Hetzner Storage Box. Use when setting up server backups, running backup
  install/init/preflight/run, configuring Storage Box SSH or BORG_PASSPHRASE,
  syncing borgmatic URLs, or enabling the first files-only backup.
---

# Backup install (Hetzner + Storage Box)

Operate Borg **on the Coolify/Hetzner server**, never as the backup destination
from a laptop. Read `docs/backup-installation.md` and `AGENTS.md`. Do not print
passphrases, Storage Box passwords, or private keys.

## Preconditions checklist

```text
- [ ] SSH to server works (Host `ubuntu` / Coolify host)
- [ ] Repo present (`/opt/py-server-manage` or `~/py-server-manage`) + `uv sync`
- [ ] Packages: borgbackup, borgmatic
- [ ] Storage Box SSH key authorized; `ssh -p 23 … exit` returns 0
- [ ] Parent dir on box exists (`mkdir borg` for `./borg/server-primary`)
- [ ] `/root/.config/py-server-manage/config.yaml` has allow_mutations + long timeout
- [ ] Real URL in BOTH `/etc/server-backup/backup.yaml` and `/etc/borgmatic/config.yaml`
- [ ] `BORG_PASSPHRASE` in `/etc/server-backup/credentials.env` (0600)
```

## Agent rules

1. Prefer dry-run before `--apply` (`install`, `init`, `run`).
2. Mutating steps need the user’s interactive sudo; this agent often cannot enter the password.
3. With sudo, use the full uv path if needed: `/home/dom/.local/bin/uv` (user-local install).
4. Under sudo, app config is `/root/.config/py-server-manage/config.yaml` — not `~dom`.
5. Never commit `/etc/server-backup/*`, keys, or passphrases. Repo examples stay placeholders.
6. Keep `backup.yaml` and borgmatic repository URLs identical.
7. Do not enable systemd backup timers until `backup run --apply` succeeds once.
8. Current `run` is files-only; do not invent DB dump steps.

## Standard workflow

### 1. Reach the server

```bash
ssh -F ~/.ssh/config -o BatchMode=yes ubuntu 'whoami; hostname; ls ~/py-server-manage /opt/py-server-manage 2>&1 | head'
```

Open Remote SSH if the user wants an interactive Cursor window:

```bash
cursor -n --folder-uri "vscode-remote://ssh-remote+ubuntu/home/dom/py-server-manage"
```

### 2. Root app config (mutations)

```bash
sudo mkdir -p /root/.config/py-server-manage
sudo tee /root/.config/py-server-manage/config.yaml >/dev/null <<'EOF'
allow_mutations: true
command_timeout_seconds: 300
EOF
```

### 3. Install scaffolding

```bash
cd ~/py-server-manage   # or /opt/py-server-manage
sudo apt-get install -y borgbackup borgmatic
sudo /home/dom/.local/bin/uv run serverops backup generate-config
sudo /home/dom/.local/bin/uv run serverops backup install --dry-run
sudo /home/dom/.local/bin/uv run serverops backup install --apply
```

### 4. Credentials and URLs (server only)

- `sudoedit /etc/server-backup/backup.yaml` → real `repository.url` + `ssh_key`
- `sudoedit /etc/server-backup/credentials.env` → `BORG_PASSPHRASE=…`
- Leave `BACKUP_*_URL` commented unless monitoring is configured
- Sync borgmatic path from backup.yaml:

```bash
sudo python3 - <<'PY'
from pathlib import Path
import yaml
backup = yaml.safe_load(Path("/etc/server-backup/backup.yaml").read_text())
url = backup["repository"]["url"]
assert "STORAGE_" not in url
path = Path("/etc/borgmatic/config.yaml")
cfg = yaml.safe_load(path.read_text())
cfg["repositories"][0]["path"] = url
path.write_text(yaml.safe_dump(cfg, sort_keys=False))
print("borgmatic URL synced")
PY
```

### 5. Storage Box parent dir + SSH test

```bash
sudo ssh -p 23 -i /root/.ssh/server-backup-storagebox \
  -o BatchMode=yes USER@HOST.your-storagebox.de mkdir borg
# ignore error if already exists

sudo ssh -p 23 -i /root/.ssh/server-backup-storagebox \
  -o BatchMode=yes -o ConnectTimeout=10 \
  USER@HOST.your-storagebox.de exit
```

### 6. Preflight → init → run

```bash
sudo /home/dom/.local/bin/uv run serverops backup preflight \
  --config /etc/server-backup/backup.yaml --require-credentials

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

## Failure playbook

| Symptom | Fix |
|---|---|
| `sudo: uv: command not found` | `sudo /home/dom/.local/bin/uv …` |
| `allow_mutations` / mutations disabled | Root `config.yaml` as above |
| `storage_host` / `STORAGE_*` in errors | Sync borgmatic URL; re-check backup.yaml |
| `command_timeout_seconds` AttributeError on BackupConfig | Use `state.config.command_timeout_seconds` / pass CLI timeout — not backup model |
| `run_command() … unexpected keyword 'env'` | `runner.run_command` must accept `env=` |
| `borgmatic list` not in read-only allowlist | Allow `("borgmatic","list")` / `("borgmatic","check")` in `runner.READ_ONLY_PREFIXES` |
| Missing parent on Storage Box | `mkdir borg` before `init` |
| Short timeouts | `command_timeout_seconds: 300` |

## Paths

| Item | Path |
|---|---|
| Preferred install root | `/opt/py-server-manage` |
| Bring-up clone | `/home/dom/py-server-manage` |
| Backup config | `/etc/server-backup/backup.yaml` |
| Credentials | `/etc/server-backup/credentials.env` |
| Borgmatic | `/etc/borgmatic/config.yaml` |
| SSH key | `/root/.ssh/server-backup-storagebox` |
| Root app config | `/root/.config/py-server-manage/config.yaml` |
| Staging | `/var/lib/server-backup/staging` |

## Related docs

- `docs/backup-installation.md` — full install
- `docs/backup-operations.md` — day-2 commands
- `docs/backup-security.md` — secret locations
- `config/backup.example.yaml` — shape only (placeholders)
