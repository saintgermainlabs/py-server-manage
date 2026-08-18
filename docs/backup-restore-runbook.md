# Backup restore runbook (draft)

Full-server recovery order (from the agent plan):

1. Provision a clean compatible Ubuntu server.
2. Patch and secure it.
3. Install Borg, borgmatic, Docker, and database clients.
4. Retrieve the Borg passphrase from **independent** storage (Vaultwarden or
   printed recovery), **not** only from this host. Vault KV
   `secret/py-server-manage/backup/borg` and `/etc/server-backup/borg-passphrase`
   live on the same Coolify box as Vault itself. If the disk is gone, you need
   an off-host copy before you can restore Vault or Vaultwarden.
5. Connect to the Storage Box and list archives.
6. Verify the repository.
7. Restore selected host configuration into a temporary directory first.
8. Install a compatible Coolify version.
9. Restore Coolify DB, original `APP_KEY`, and SSH keys.
10. Restore `/srv/projects`, `/opt`, and `/home/dom/projects`.
11. Restore approved volumes.
12. Recreate/import databases.
13. Start services in dependency order.
14. Validate permissions and app behaviour.
15. Update DNS / Cloudflare / Tailscale as needed.

**Never overwrite production paths automatically.** Phase 1–2 does not yet implement `serverops backup restore`.
