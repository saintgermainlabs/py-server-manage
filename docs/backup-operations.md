# Backup operations

## Discover (laptop or server)

```bash
uv run serverops backup discover
```

Review:

- `data/inventory/backup-inventory.yaml`
- `data/reports/backup-inventory.md`
- `data/inventory/system-state.yaml`
- `data/reports/system-state.md`

On the Hetzner host, prefer running discover after git deploy so mandatory paths exist.

## Generate config / install / preflight (server)

```bash
cd /opt/py-server-manage
uv run serverops backup generate-config
uv run serverops backup install --dry-run
uv run serverops backup preflight
```

See [backup-installation.md](backup-installation.md).

## Later commands

`run`, `check`, `restore`, `status`, and `report` remain stubbed until Borg repo init and dump pipelines land.
