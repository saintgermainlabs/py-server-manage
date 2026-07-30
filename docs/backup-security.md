# Backup security

- Never commit Borg passphrases, Storage Box keys, database passwords, or Coolify `APP_KEY`.
- Recommended runtime locations (later phases):
  - `/etc/server-backup/credentials.env` (`0600`, `root:root`)
  - `/root/.ssh/server-backup-storagebox`
  - `/etc/borgmatic/config.yaml`
- Discovery output is redacted before write.
- systemd units must use `UMask=0077` when installed.
