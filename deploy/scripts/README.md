# Deploy scripts

- [`install-backup-system.sh`](install-backup-system.sh) — wrapper around `serverops backup install` (defaults to `--dry-run`).

Run on the Hetzner host after cloning this repo to `/opt/py-server-manage` and `uv sync --all-extras`.

See [docs/backup-installation.md](../../docs/backup-installation.md).
