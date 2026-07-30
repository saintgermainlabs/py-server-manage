# Backup plan (summary)

This repository implements a **host-level** backup system for the Coolify Hetzner server using BorgBackup, borgmatic, and systemd.

Authoritative detailed plan:

- [`AGENT-BACKUP-IMPLEMENTATION-PLAN.md`](../AGENT-BACKUP-IMPLEMENTATION-PLAN.md)

## Current status (Phase 1–3 foundation)

- Package skeleton and CLI group: `serverops backup`
- Read-only `serverops backup discover` / `inventory`
- On-server deploy docs: git clone to `/opt/py-server-manage`
- `generate-config`, `install --dry-run/--apply`, and `preflight`
- Example configs under `config/backup.example.yaml` and `config/borgmatic.example.yaml`

## Not yet implemented

Storage Box `borg init`, enabling production systemd timers with live credentials, database dump pipeline, and first full `backup run`.

## Next inputs required from operators

- Storage Box sub-account hostname and username
- SSH key path and Borg passphrase location
- Which databases are required vs disposable caches
- Acceptable downtime for any volume quiesce hooks
