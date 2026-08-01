## Vault Agent vs Transit snapshot

Two complementary ways to handle `databases.yaml`:

1. **Transit encrypt** (like inventories): build on the laptop from decrypted
   Coolify/backup inventories → `data/inventory/databases.yaml` (placeholders) →
   `serverops backup encrypt-databases` → commit `.enc`.
2. **Vault Agent** (this directory): render `/etc/server-backup/databases.yaml`
   on the backup host with live KV credentials at runtime.

Prefer Transit for the git-audited allowlist structure; prefer Agent/KV for
rotating passwords without re-committing ciphertext.

| Artifact | Path |
|---|---|
| Committed example (placeholders) | `config/databases.example.yaml` |
| Vault Agent template | `deploy/vault-agent/templates/databases.yaml.ctmpl` |
| Agent config example | `deploy/vault-agent/backup-databases.hcl.example` |
| Rendered live file (server only) | `/etc/server-backup/databases.yaml` |

### KV layout

One secret per database id:

```text
secret/data/py-server-manage/backup/databases/<id>
  username
  password
  database
```

Example write (interactive OIDC; do not paste into chat logs):

```bash
export VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
vault kv put secret/py-server-manage/backup/databases/coolify-db \
  username='…' password='…' database='coolify'
```

### Render on the backup host

1. Fill non-secret identity fields in the `.ctmpl` (container names / Coolify UUIDs).
2. Install agent config from `backup-databases.hcl.example`.
3. Ensure AppRole can `read` those KV paths (least privilege).
4. Start Vault Agent; confirm `/etc/server-backup/databases.yaml` is `0600`.
5. Never commit the rendered file.

Until the native dump pipeline lands, this file is the allowlist contract;
`serverops backup discover-databases` can compare running containers against it.
