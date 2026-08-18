# Server-backup AppRole (Borg passphrase)

Create this role **after Vault is unsealed**. Do not paste RoleIDs, SecretIDs,
or the Borg passphrase into chat logs.

The laptop AppRole `py-server-manage` is batch/use-limited and is **not** for
the long-running Vault Agent. The backup host gets its own role.

## KV source of truth

```text
secret/py-server-manage/backup/borg
  passphrase = <borg repo passphrase>
```

Vault Agent renders `/etc/server-backup/borg-passphrase` (`0600`). borgmatic
should use:

```yaml
encryption_passcommand: cat /etc/server-backup/borg-passphrase
```

Until that file exists, keep `printenv BORG_PASSPHRASE` plus
`/etc/server-backup/credentials.env`. If Vault is sealed, the last rendered
file still unlocks Borg; a live `vault kv get` would fail.

## 1. Policy + AppRole (interactive OIDC on the laptop)

```bash
export VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
vault status          # Sealed must be false
vault login -method=oidc role=inventory

cd /path/to/py-server-manage
vault policy write server-backup deploy/vault/policies/server-backup.hcl

vault write auth/approle/role/server-backup \
  token_policies="server-backup" \
  token_type="service" \
  token_ttl="1h" \
  token_max_ttl="4h" \
  secret_id_ttl="0" \
  secret_id_num_uses=0

vault read -field=role_id auth/approle/role/server-backup/role-id \
  | install -m 0600 /dev/stdin /tmp/server-backup-role-id

vault write -field=secret_id -f auth/approle/role/server-backup/secret-id \
  | install -m 0600 /dev/stdin /tmp/server-backup-secret-id
```

Copy those two files to the host as root-only:

```text
/etc/serverops/credentials/vault-role-id
/etc/serverops/credentials/vault-secret-id
```

Then shred the laptop copies.

## 2. Seed KV from the existing credentials file (on the host)

The live `py-server-manage` AppRole policy is **Transit-only** (no KV write).
Seed KV with an admin/OIDC token that can write
`secret/data/py-server-manage/backup/borg`, or use `vault kv put` from a
privileged laptop session. Do not copy a root token in shell history.

Mint a short-lived token (or use OIDC) then:

```bash
vault print token | install -m 0600 /dev/stdin /tmp/vault-token-seed
scp /tmp/vault-token-seed ubuntu:/home/dom/.vault-token-seed
shred -u /tmp/vault-token-seed
```

On the host:

```bash
chmod 600 /home/dom/.vault-token-seed
./scripts/backup/seed-borg-passphrase-to-vault.sh
shred -u /home/dom/.vault-token-seed
```

## 3. Start Agent and switch borgmatic

Install `deploy/vault-agent/backup-borg.hcl.example` as
`/etc/vault-agent.d/backup-borg.hcl` and the unit
`deploy/systemd/vault-agent-backup.service`. That unit must run the Vault
image as `--user 0:0 --entrypoint vault --cap-add IPC_LOCK` or AppRole files
mode `0600` are unreadable. Confirm `/etc/server-backup/borg-passphrase` is
`0600` and non-empty (do not `cat` it). Live map: [docs/backup-live.md](../../docs/backup-live.md).

Then set borgmatic `encryption_passcommand` to
`cat /etc/server-backup/borg-passphrase` and `daemon-reload`. Keep
`credentials.env` until one successful `borgmatic rlist`.
