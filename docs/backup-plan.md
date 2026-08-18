# Backup plan (summary)

This repository implements a **host-level** backup system for the Coolify Hetzner server using BorgBackup, borgmatic, and systemd.

Authoritative detailed plan:

- [`AGENT-BACKUP-IMPLEMENTATION-PLAN.md`](../AGENT-BACKUP-IMPLEMENTATION-PLAN.md)

## Current status (live, 2026-08-18)

Production files backup is **on**: distro `borgmatic.timer` → Storage Box
`./borg/server-primary`, passphrase from Vault KV via Agent. Runtime map:
[backup-live.md](backup-live.md).

- Package skeleton and CLI group: `serverops backup`
- Read-only `serverops backup discover` / `inventory`
- Server clone today is `/home/dom/py-server-manage` (preferred `/opt` still documented)
- `generate-config`, `install --dry-run/--apply`, and `preflight`
- Example configs under `config/backup.example.yaml` and `config/borgmatic.example.yaml`
- First Vault-backed archive: `hetzner-primary-full-2026-08-18T22:38:50`

## Not yet the nightly path

ServerOps `server-backup.timer` and a complete native dump pipeline for
MySQL/MariaDB/Mongo. PostgreSQL dump helpers exist in the CLI but the live
nightly job is still files-only borgmatic.

## Next inputs required from operators

- Storage Box sub-account hostname and username
- SSH key path and Borg passphrase location
- Which databases are required vs disposable caches
- Acceptable downtime for any volume quiesce hooks
