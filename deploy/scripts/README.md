# Deploy scripts

- [`install-backup-system.sh`](install-backup-system.sh) — wrapper around `serverops backup install` (defaults to `--dry-run`).

Run on the Hetzner host after cloning this repo to `/opt/py-server-manage` and `uv sync --all-extras`.

After install, configure Storage Box credentials, then use `serverops backup init` /
`backup run --apply` as described in [docs/backup-installation.md](../../docs/backup-installation.md).
Do not enable systemd backup timers until the database dump pipeline lands.
