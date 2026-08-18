# Live backup runtime (Ubuntu-24)

Recorded **2026-08-18**. This is what is actually running on the Coolify
Hetzner host. Example configs in git stay placeholders; live URLs and secrets
stay on the server.

Do not print Borg passphrases, Vault tokens, AppRole SecretIDs, or Storage Box
private keys.

## Topology

```text
Laptop  (/home/god/obsidian-vaults, branch flatten)
   │  Syncthing (live files)
   ▼
Coolify host  SSH alias `ubuntu`  (user `dom`, hostname Ubuntu-24)
   /srv/data/obsidian-vault/{vaults,agent}   live Obsidian
   /home/dom/py-server-manage                git clone (not /opt)
   borgmatic.timer  →  borgmatic.service     nightly files archive
   vault-agent-backup.service                renders Borg passphrase
   HashiCorp Vault  https://vault.tiger-bushmaster.ts.net
   Vaultwarden      human recovery copy only
        │  borg over SSH port 23
        ▼
Hetzner Storage Box
   ssh://u618588@u618588.your-storagebox.de:23/./borg/server-primary
```

Do **not** enable a second restic timer for the vaults. Production backup is
this borgmatic job.

Keep **Syncthing** for laptop↔server live files. Do not add Obsidian LiveSync
or official Obsidian Headless (`ob`) unless explicitly requested.

## Access notes

| Fact | Detail |
|---|---|
| SSH | Host `ubuntu` / `Ubuntu-24`, user `dom` |
| `dom` groups | `docker`, `sudo` (sudo needs a password) |
| Root SSH key `id_ed25519_server` | Missing; agents edit `/etc` via Docker bind-mounts |
| Journal for system units | `dom` often cannot read it; use `docker … nsenter -t 1 … journalctl` |

## What runs nightly

| Unit | State | Role |
|---|---|---|
| `borgmatic.timer` | enabled | Distro timer: `OnCalendar=daily`, `RandomizedDelaySec=3h` |
| `borgmatic.service` | oneshot | `/usr/bin/borgmatic` after `ExecStartPre=sleep 1m` |
| `vault-agent-backup.service` | enabled | Docker Vault Agent; keeps passphrase file fresh |
| `server-backup.timer` | **disabled** | ServerOps unit; has `EnvironmentFile` but is not the nightly job |

Drop-in `/etc/systemd/system/borgmatic.service.d/credentials.conf` still loads
`EnvironmentFile=-/etc/server-backup/credentials.env` as a fallback for
`printenv BORG_PASSPHRASE`. Live borgmatic uses the Vault-rendered file instead.

## Passphrase

| Layer | Path / setting |
|---|---|
| Source of truth | Vault KV v2 `secret/py-server-manage/backup/borg` field `passphrase` |
| Agent config | `/etc/vault-agent.d/backup-borg.hcl` |
| AppRole files | `/etc/serverops/credentials/vault-role-id` and `vault-secret-id` (`0600`) |
| Rendered cache | `/etc/server-backup/borg-passphrase` (`0600` root) |
| borgmatic | `encryption_passcommand: cat /etc/server-backup/borg-passphrase` |
| Fallback | `/etc/server-backup/credentials.env` (`0600`) `BORG_PASSPHRASE=` |
| Human recovery | Vaultwarden (do **not** use for unattended `encryption_passcommand`) |

If Vault is **sealed**, nightly borgmatic should still work from the last
rendered passphrase file. A live `vault kv get` would fail. Unseal from a local
terminal (Shamir **3 of 5**); never paste unseal keys into chat:

```bash
export VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
vault operator unseal   # ×3
vault status            # Sealed must be false
```

### AppRoles

| Role | Use | Notes |
|---|---|---|
| `server-backup` | Vault Agent on the host | Service tokens; SecretID TTL unlimited; policy `server-backup` (read KV backup paths) |
| `py-server-manage` | Laptop inventory Transit | Batch token, SecretID 10 uses / 24h. Live ACL is **Transit only** (`transit/encrypt|decrypt/inventory`). Do not use for the Agent |

Policy HCL: `deploy/vault/policies/server-backup.hcl`.

### Vault Agent Docker gotchas

The `hashicorp/vault:1.17` image entrypoint drops from root to user `vault`,
which cannot read `0600` AppRole files or write `/run/vault-agent-backup`.
The live unit therefore uses:

```text
--user 0:0 --cap-add IPC_LOCK --entrypoint vault
```

Template bind-mount maps
`/home/dom/py-server-manage/deploy/vault-agent/templates` to
`/opt/py-server-manage/deploy/vault-agent/templates` inside the container
(HCL still names the `/opt/...` source).

## Borgmatic sources (live)

`/etc/borgmatic/config.yaml` includes at least:

- `/data/coolify`
- `/srv/projects`
- `/opt`
- `/home/dom/projects`
- `/etc`
- `/usr/local/bin`, `/usr/local/sbin`
- `/root/.ssh`
- `/srv/data/obsidian-vault/vaults`
- `/srv/data/obsidian-vault/agent`

Obsidian-related excludes: `**/.git`, `**/.github`, `**/.gitea`, `**/.stfolder`,
`**/.stversions`, `**/.trash`, `**/documentation-imports`, `**/workspace.json`,
`**/workspace-mobile.json`, `**/node_modules`.

SSH: `ssh -i /root/.ssh/server-backup-storagebox -p 23 -o BatchMode=yes`.

## Start / inspect a backup

Stock unit sleeps **one minute** before `borgmatic` starts.

```bash
# On the host, as root (or docker nsenter -t 1 …):
systemctl start --no-block borgmatic.service
journalctl -u borgmatic.service -f
borgmatic list --last 3
borgmatic info --archive hetzner-primary-full-YYYY-MM-DDTHH:MM:SS
```

Do not `cat` passphrase files. Confirm the rendered file with
`stat -c '%a %s %U' /etc/server-backup/borg-passphrase` (mode `600`, size &gt; 0).

## Known archives (as of 2026-08-18)

| Archive | Notes |
|---|---|
| `hetzner-primary-full-2026-08-01T04:10:57` | First Storage Box archive (before vault paths / Vault passcommand) |
| `hetzner-primary-full-2026-08-18T22:38:50` | First Vault-backed run; includes Obsidian `vaults` + `agent` (~3.5k files, ~103 MB original) |

## Related docs

- [backup-operations.md](backup-operations.md) — CLI discover / run
- [backup-installation.md](backup-installation.md) — bring-up
- [backup-security.md](backup-security.md) — secret locations
- [backup-restore-runbook.md](backup-restore-runbook.md) — recovery order
- [../deploy/vault/README.md](../deploy/vault/README.md) — AppRole bootstrap
- [../deploy/vault-agent/README.md](../deploy/vault-agent/README.md) — Agent templates
- [VAULT.md](VAULT.md) — OIDC vs AppRole
