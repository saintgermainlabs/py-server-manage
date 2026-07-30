# Inventory Security

## Threat model

Inventory snapshots produced by `serverops` may contain hostnames, IP
addresses, container names, service versions, and other operational metadata.
None of that is public, but none of it rises to the level of credentials or
cryptographic key material.

The primary risk is **accidental git commit** of a plaintext inventory file.

## Default protection: `.gitignore`

All output directories are gitignored:

| Directory | Purpose |
|---|---|
| `data/inventory/` | Raw YAML/JSON inventories |
| `data/reports/` | Diagnostic reports |
| `data/transformed/` | Dashboard / template outputs |
| `data/backups/` | Backup manifests |
| `data/restore-tests/` | Restore-test records |

This is the **recommended baseline**. For inventories that never leave the
server, keeping them gitignored is sufficient.

## Optional: Vault Transit encryption

If you need to:

- Commit encrypted snapshots to a git repository for auditing, or
- Transfer snapshots to a second host via S3 or another channel,

you can encrypt them with HashiCorp Vault's [Transit secrets engine].

### Why Vault Transit?

| Criterion | Vault Transit | Age/GPG (local keys) | Symmetric passphrase |
|---|---|---|---|
| Key rotation without re-encrypting data | ✅ via `rewrap` | ❌ manual | ❌ manual |
| Key is never on the application host | ✅ | ❌ | ❌ |
| Audit log of every encrypt/decrypt | ✅ | ❌ | ❌ |
| Uses existing `hvac` dependency | ✅ | ❌ requires `pyrage` | ❌ |
| Already installed on the server | ✅ | maybe | yes |

Vault Transit is purpose-built for this pattern: the plaintext is never stored
by Vault, key material never leaves Vault, and every operation is logged.

### Setup

```bash
# Enable the Transit engine (once per Vault server)
vault secrets enable transit

# Create a named key for inventories
vault write -f transit/keys/inventory
```

### Encrypt an inventory file

**Local laptop (mise):** put `VAULT_ADDR`, `VAULT_ROLE_ID`, and `VAULT_SECRET_ID` in
`.env.local`. [`mise.toml`](../mise.toml) loads them automatically (mise redacts
`.env.local` in task output).

```bash
mise run cli -- inventory encrypt data/inventory/coolify-inventory.yaml
```

**Server or shell exports:**

```bash
# AppRole (recommended for automation)
export VAULT_ADDR=https://vault.example.com:8200
export VAULT_ROLE_ID=your-role-id
export VAULT_SECRET_ID=your-secret-id

serverops inventory encrypt data/inventory/coolify-inventory.yaml
# → writes data/encrypted/inventory/coolify-inventory.yaml.enc
```

For interactive use you may set `VAULT_TOKEN` instead; the CLI tries the token
first, then AppRole credentials from the environment or `--vault-role-id` /
`--vault-secret-id`. Credential files are supported via `VAULT_ROLE_ID_FILE` and
`VAULT_SECRET_ID_FILE`. TLS: `VAULT_CACERT`, or `VAULT_SKIP_VERIFY=1` to disable
verification (not recommended in production).

The `.enc` file contains only the opaque `vault:v1:…` ciphertext string.
It is safe to commit or transfer.

### Decrypt

```bash
serverops inventory decrypt data/encrypted/inventory/coolify-inventory.yaml.enc
# → writes data/inventory/coolify-inventory.yaml
```

### Key options

| Option | Default | Description |
|---|---|---|
| `--vault-addr` | `$VAULT_ADDR` (else tailnet default in `serverops.vault`) | Vault server URL |
| `--vault-token` | `$VAULT_TOKEN` | Optional token (tried before AppRole) |
| `--vault-role-id` | `$VAULT_ROLE_ID` | AppRole role ID |
| `--vault-secret-id` | `$VAULT_SECRET_ID` | AppRole secret ID |
| `-o / --output` | `data/encrypted/inventory/` / `data/inventory/` | Override output path |

Transit encryption uses key `inventory` (override with `VAULT_TRANSIT_KEY`) on
mount `transit` (override with `VAULT_TRANSIT_MOUNT`). See `.env.example`.

### Authentication versus authorization errors

- **Authentication** failures (invalid AppRole, missing `auth.client_token`, or
  `Vault authentication failed`) mean Vault did not accept the credentials.
- **Authorization** failures (HTTP 403 on Transit) mean login succeeded but the
  token lacks `update` on `transit/encrypt/inventory` or
  `transit/decrypt/inventory`. Repair the `py-server-manage` ACL policy on the
  server (see [docs/VAULT.md](VAULT.md)).

### Git: plaintext versus `.enc` files

By default, `data/inventory/*` is gitignored so **plaintext** inventories are not
committed. Transit ciphertext under `data/encrypted/inventory/*.enc` is opaque
and is tracked deliberately so encrypted snapshots can ship with the repository.

Never commit `.env.local`, AppRole credentials, or decrypted outputs.

### Security guarantees

- Vault tokens, role IDs, and secret IDs are **never** logged, printed, or
  included in exception messages.
- Authentication uses the `hvac` library (AppRole login or a supplied token).
- Vault itself never stores the plaintext.
- Key rotation and access revocation are handled entirely within Vault.

[Transit secrets engine]: https://developer.hashicorp.com/vault/docs/secrets/transit
