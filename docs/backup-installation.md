# Backup installation (remote Hetzner host)

BorgBackup **must** run on the Coolify server, not on a developer laptop.
Develop on your laptop, push to git, then deploy and operate backups on the server.

## Architecture

```text
Laptop (dev)  →  git push  →  Git remote
                                  ↓
                         Hetzner Ubuntu host
                    /opt/py-server-manage (this repo)
                    serverops + borg + borgmatic
                    systemd timers (later)
                                  ↓
                         Hetzner Storage Box :23
```

## Deploy the repo on the server

As a sudo-capable user (then use root for backup install):

```bash
sudo mkdir -p /opt
sudo git clone YOUR_GIT_URL /opt/py-server-manage
cd /opt/py-server-manage
sudo uv sync --all-extras
```

Later updates:

```bash
cd /opt/py-server-manage
sudo git pull
sudo uv sync --all-extras
```

## System packages

On the server:

```bash
sudo apt-get update
sudo apt-get install -y borgbackup borgmatic \
  postgresql-client default-mysql-client mongodb-database-tools
```

Adjust DB clients to match engines you actually run.

## Generate staged configs (safe)

From the repo on the server:

```bash
cd /opt/py-server-manage
sudo uv run serverops backup generate-config
```

Writes under `data/backups/generated/`:

- `borgmatic.yaml`
- `credentials.env.example`
- `server-backup.service` / `.timer`
- `server-backup-check.service` / `.timer`
- `backup.yaml` (copy of resolved settings)

Review those files. Fill Storage Box placeholders **only** in server-local copies later.

## Preview install (default dry-run)

```bash
sudo uv run serverops backup install
# or explicitly:
sudo uv run serverops backup install --dry-run
```

Shows planned package checks, directory creation, and file copies. Makes **no** changes.

Apply (still refuses to overwrite live configs without `--force`):

```bash
sudo uv run serverops backup install --apply
```

Or use the wrapper script:

```bash
sudo ./deploy/scripts/install-backup-system.sh --dry-run
sudo ./deploy/scripts/install-backup-system.sh --apply
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

## Storage Box credentials (server only — never commit)

1. Create a Storage Box **sub-account** in Hetzner Robot/Cloud.
2. On the **server**, generate a dedicated key if needed:

```bash
sudo ssh-keygen -t ed25519 -f /root/.ssh/server-backup-storagebox -N ""
```

3. Authorize the public key for the Storage Box sub-account.
4. Edit `/etc/server-backup/backup.yaml` repository URL:

```yaml
repository:
  url: ssh://uXXXXX-sub1@uXXXXX-sub1.your-storagebox.de:23/./borg/server-primary
  ssh_key: /root/.ssh/server-backup-storagebox
```

5. Put the Borg passphrase in `/etc/server-backup/credentials.env`:

```bash
BORG_PASSPHRASE=...
```

## First on-server checks

```bash
cd /opt/py-server-manage
sudo uv run serverops backup discover
sudo uv run serverops backup preflight --config /etc/server-backup/backup.yaml
```

Preflight validates tools, mandatory paths, staging dirs, Docker, SSH key presence, and Storage Box host:23 when the URL is not a placeholder.

## Not yet automated in this phase

- `borg init` / first archive
- Enabling systemd timers with production credentials
- Database dump pipeline

See [backup-operations.md](backup-operations.md) and [AGENT-BACKUP-IMPLEMENTATION-PLAN.md](../AGENT-BACKUP-IMPLEMENTATION-PLAN.md).
