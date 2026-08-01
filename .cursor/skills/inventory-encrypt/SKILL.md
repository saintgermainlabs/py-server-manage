---
name: inventory-encrypt
description: >-
  Produce Coolify and Tailscale inventories, encrypt them with Vault Transit,
  build/encrypt the databases allowlist, and prepare encrypted snapshots for
  git. Use when collecting inventories, encrypting with Vault, building
  databases.yaml, refreshing AppRole/Tailscale credentials, or preparing
  encrypted inventory files before a push.
---

# Inventory produce + Vault encrypt

Project workflow for `py-server-manage`: collect plaintext inventories under
`data/inventory/` (gitignored), encrypt with Vault Transit into
`data/encrypted/inventory/*.enc` (safe to commit), then push.

Read `AGENTS.md` and `src/serverops/vault/AGENTS.md` before changing Vault code.
Do not print credentials, tokens, RoleIDs, or SecretIDs.

## Preconditions checklist

Copy and track:

```text
- [ ] `.env.local` has Coolify + Tailscale + Vault AppRole vars (never commit)
- [ ] Tailscale is up (`tailscale status` shows nodes, not "stopped")
- [ ] Vault MagicDNS resolves (`getent hosts vault.tiger-bushmaster.ts.net`)
- [ ] `VAULT_SECRET_ID` is fresh (use-limited; mint new if AppRole login fails)
- [ ] Unset stale `VAULT_TOKEN` / ignore expired `~/.vault-token`
```

Credentials live in `.env.local` (loaded by `mise.toml`). Prefer:

```bash
mise run cli -- <args>
# equivalent: uv run serverops <args> with mise env
```

Always `unset VAULT_TOKEN` before encrypt if a stale token may be in the shell.

## Standard workflow

### 1. Verify reachability

```bash
/usr/bin/tailscale status | head
getent hosts vault.tiger-bushmaster.ts.net
curl -sS -o /dev/null -w '%{http_code}\n' --connect-timeout 8 \
  https://vault.tiger-bushmaster.ts.net/v1/sys/health
```

If Tailscale is stopped: ask the user to run `sudo tailscale up` (needs their password). Do not mint Vault SecretIDs or rotate credentials without explicit approval.

### 2. Produce inventories

```bash
unset VAULT_TOKEN

# Coolify → data/inventory/coolify-inventory.yaml
mise run cli -- coolify inventory

# Tailscale API (needs TAILSCALE_API_KEY or OAuth client id+secret)
mise run cli -- tailscale api-inventory \
  -o data/inventory/tailscale-api-inventory.yaml --no-details

# Nodes-only view from API inventory
mise run cli -- tailscale nodes \
  data/inventory/tailscale-api-inventory.yaml \
  -o data/inventory/tailscale-api-nodes.yaml

# Local Tailscale CLI inventory (uses system /usr/bin/tailscale)
mise run cli -- tailscale inventory --no-ping
```

Optional host/backup snapshots (already under `data/inventory/` when generated):

- `system-state.yaml`
- `backup-inventory.yaml`

### 3. Encrypt with Vault Transit

```bash
unset VAULT_TOKEN

for f in \
  data/inventory/coolify-inventory.yaml \
  data/inventory/tailscale-api-inventory.yaml \
  data/inventory/tailscale-api-nodes.yaml \
  data/inventory/tailscale-inventory.yaml \
  data/inventory/system-state.yaml \
  data/inventory/backup-inventory.yaml \
  data/inventory/databases.yaml
do
  [ -f "$f" ] || continue
  mise run cli -- inventory encrypt "$f"
done
```

Optional database allowlist (after decrypting Coolify / backup inventories):

```bash
mise run cli -- backup build-databases-allowlist --dry-run
mise run cli -- backup build-databases-allowlist --apply
mise run cli -- backup encrypt-databases
# → data/encrypted/inventory/databases.yaml.enc
```

Credentials in `databases.yaml` must stay `VAULT_PLACEHOLDER_*` (or be injected
from KV at dump time). Do not commit plaintext passwords.

Outputs: `data/encrypted/inventory/<basename>.enc` (opaque `vault:v1:…` ciphertext).
Plaintext is **not** deleted.

### 4. Git safety before push

```bash
# Plaintext must stay ignored
git check-ignore -v data/inventory/*.yaml

# Ciphertext must be addable
git add -n data/encrypted/inventory/*.enc
git status --short data/encrypted/inventory/
```

Rules:

- Commit `data/encrypted/inventory/*.enc` only.
- Never commit `.env`, `.env.local`, plaintext under `data/inventory/`, or Vault tokens.
- Do not commit unless the user asks.

## Credential refresh (user actions)

### Vault AppRole SecretID (required for encrypt)

Role `py-server-manage` uses short TTL and limited uses (`secret_id_num_uses=10`).
When encrypt fails with AppRole login / SecretID exhaustion:

```bash
export VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
vault login -method=oidc
vault write -field=secret_id -f \
  auth/approle/role/py-server-manage/secret-id
```

User pastes the value into `.env.local` as `VAULT_SECRET_ID=…`, then agent retries encrypt.
See `docs/VAULT.md`.

### Tailscale API / OAuth

When API inventory returns HTTP 401:

- Refresh `TAILSCALE_API_KEY`, **or**
- Refresh `TAILSCALE_OAUTH_CLIENT_ID` + `TAILSCALE_OAUTH_CLIENT_SECRET`

in `.env.local`. Prefer API key for simple inventory collection. CLI inventory
(`tailscale inventory`) still works without API credentials when Tailscale is up.

### Coolify

Needs `COOLIFY_URL` and `COOLIFY_API_TOKEN` (or `COOLIFY_API_KEY`).

## Failure playbook

| Symptom | Likely cause | Fix |
|---|---|---|
| `Could not resolve host: vault…` | Tailscale stopped / no MagicDNS | `sudo tailscale up`; recheck DNS |
| AppRole login failed / SecretID use limit | Exhausted or expired SecretID | Mint new SecretID; update `.env.local` |
| `Vault token is invalid or expired` | Stale `VAULT_TOKEN` | `unset VAULT_TOKEN`; rely on AppRole |
| Tailscale API HTTP 401 | Bad/expired API key or OAuth secret | Refresh Tailscale credentials |
| `No such command 'status'` / wrong tailscale | PyPI `tailscale` shadowed CLI | Use `/usr/bin/tailscale`; package removed from deps |
| Encrypt writes but git ignores `.enc` | Missing gitignore exception | Ensure `!data/encrypted/inventory/*.enc` |

## Paths and defaults

| Artifact | Path |
|---|---|
| Plaintext inventories | `data/inventory/*.yaml` (gitignored) |
| Encrypted inventories | `data/encrypted/inventory/*.enc` (commit-able) |
| Vault address | `VAULT_ADDR` → `https://vault.tiger-bushmaster.ts.net` |
| Transit mount/key | `transit` / `inventory` |

Helper: `serverops.paths.inventory_path`, `encrypted_inventory_output_path`.

## Agent rules for this workflow

1. Prefer `mise run cli -- …` so `.env.local` loads.
2. Never echo secret values; report only set/unset and lengths if needed.
3. Do not mint SecretIDs, rotate Vault policies, or run `vault write` for credentials unless the user explicitly asks.
4. Do not push or commit unless asked.
5. After credential refresh, re-run produce (if needed) then encrypt all targets in one pass.
6. Confirm plaintext remains gitignored and `.enc` files are staged only when the user wants a commit.

## Related docs

- `docs/inventory-security.md` — threat model and encrypt CLI
- `docs/VAULT.md` — AppRole / OIDC / SecretID rotation
- `src/serverops/vault/AGENTS.md` — Vault module boundaries
- `README.md` — local mise + `.env.local` setup
