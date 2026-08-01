# Backup security

- Never commit Borg passphrases, Storage Box keys, database passwords, or Coolify `APP_KEY`.
- Runtime locations (server only):
  - `/etc/server-backup/credentials.env` (`0600`, `root:root`) — `BORG_PASSPHRASE`
  - `/etc/server-backup/databases.yaml` (`0600`) — allowlist + DB creds rendered by Vault Agent
  - `/root/.ssh/server-backup-storagebox` — dedicated key for the Storage Box
  - `/etc/server-backup/backup.yaml` and `/etc/borgmatic/config.yaml` — real URLs stay off-git
- Database allowlist template: `deploy/vault-agent/templates/databases.yaml.ctmpl`
  and Transit snapshot `data/encrypted/inventory/databases.yaml.enc`
  (see `config/databases.example.yaml`). Never commit plaintext with real passwords.
  Build with `backup build-databases-allowlist`; encrypt with `backup encrypt-databases`.
- Optional monitoring ping URLs (`BACKUP_*_URL`) are not required for init/run.
- Discovery output is redacted before write.
- systemd units must use `UMask=0077` when installed.
- Prefer a Storage Box **sub-account** with only the backup SSH key authorized.
- Store the Borg passphrase in a password manager; loss means unrecoverable archives.
