# Generated unit templates live under data/backups/generated/ after:
#   serverops backup generate-config
#
# install --apply copies them to /etc/systemd/system when run on the server.
# Do not enable timers until Storage Box credentials and preflight succeed.
#
# vault-agent-backup.service runs Vault Agent (via Docker) to render
# /etc/server-backup/borg-passphrase from KV. Enable only after Vault is
# unsealed and AppRole files exist under /etc/serverops/credentials/.
#
# Checked-in drop-in: `borgmatic.service.d/credentials.conf`
# The Ubuntu borgmatic package timer (`borgmatic.timer`) does not load
# `/etc/server-backup/credentials.env`. Without this drop-in, nightly
# `encryption_passcommand: printenv BORG_PASSPHRASE` fails.
