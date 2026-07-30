# IDE Handoff: Vault Integration Update

Use this document as the current source of truth for the HashiCorp Vault work in
`py-server-manage`.

## Objective

The project encrypts generated inventory files with HashiCorp Vault Transit.
Human users authenticate through Authentik OIDC. The Python application
authenticates non-interactively with AppRole.

Do not redesign the authentication model:

- **Humans:** Authentik OIDC role `inventory`
- **Application:** AppRole `py-server-manage`
- **Encryption engine:** Vault Transit
- **Transit key:** `inventory`
- **Vault address:** `https://vault.tiger-bushmaster.ts.net`

## Confirmed working state

The complete application path has now been tested successfully.

AppRole authentication returned a batch token whose effective capabilities
included:

```text
transit/encrypt/inventory: update
```

The following command completed successfully:

```bash
mise run cli -- inventory encrypt data/tailscale-api-nodes.yaml
```

Result:

```text
Encrypted data/tailscale-api-nodes.yaml ->
data/tailscale-api-nodes.yaml.enc
```

Therefore:

- mise is providing the expected Vault configuration.
- AppRole authentication is working.
- Vault is reachable from the development environment.
- Transit is mounted and the `inventory` key exists.
- The repository's encryption command is successfully calling Vault.
- No Python-side fix is required for the earlier `403`.

## Root cause of the earlier failure

Encryption initially failed with:

```text
403 permission denied
```

The AppRole login itself was successful. Its token carried the policy names:

```text
default
py-server-manage
```

However, the `py-server-manage` ACL policy did not exist in Vault. A policy name
on a token does not grant useful capabilities when the corresponding ACL policy
is absent. Consequently:

```bash
vault token capabilities transit/encrypt/inventory
```

returned:

```text
deny
```

This was a Vault server ACL problem, not a problem with:

- `hvac`
- the AppRole credentials
- mise
- the CLI argument handling
- Base64 encoding
- `serverops` Transit code

## Server-side policy created

Using a root Vault session, the following ACL policy was created under the name
`py-server-manage`:

```hcl
path "transit/encrypt/inventory" {
  capabilities = ["update"]
}

path "transit/decrypt/inventory" {
  capabilities = ["update"]
}
```

After creating that policy, a fresh AppRole capability check returned:

```text
update
```

The same application encryption command then succeeded without changing
`.env.local`.

This policy is server configuration. Do not attempt to create or repair it
automatically from normal application startup. The AppRole must not be allowed
to administer its own policies.

## Important distinction: authentication versus authorization

The IDE should preserve this distinction in code, errors, tests, and
documentation:

1. AppRole exchanges a Role ID and Secret ID for a Vault token.
2. Successful login proves authentication only.
3. Vault evaluates the token's named ACL policies for each requested path.
4. Transit encryption requires `update` on:

   ```text
   transit/encrypt/inventory
   ```

5. Transit decryption requires `update` on:

   ```text
   transit/decrypt/inventory
   ```

A successful `client.is_authenticated()` check does not guarantee permission to
encrypt or decrypt.

## Repository review requested

Inspect the current repository before editing. Preserve working behavior and
make only changes that are still necessary.

### 1. Dependency

Confirm `hvac` is declared in `pyproject.toml` and locked in `uv.lock`.

If it is not present:

```bash
uv add hvac
```

Do not add a second HTTP implementation with `requests` if `hvac` already owns
Vault communication.

### 2. Vault module placement

Vault is a first-class external integration, not a generic utility. The desired
long-term location is:

```text
src/serverops/vault/
├── __init__.py
├── auth.py
├── client.py
├── errors.py
└── transit.py
```

If the working implementation is currently contained in
`src/serverops/utils/vault.py`, do not perform a risky move merely for cosmetic
reasons. First inspect imports and tests. Migrate it only as a coherent,
tested refactor.

Suggested responsibilities:

| File | Responsibility |
| --- | --- |
| `client.py` | Construct and configure `hvac.Client` |
| `auth.py` | AppRole login and token validation |
| `transit.py` | Base64 conversion and Transit encrypt/decrypt |
| `errors.py` | Project-specific, actionable Vault errors |

Do not add `kv.py` until the application actually uses KV.

### 3. Configuration

Configuration should support:

```dotenv
VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
VAULT_ROLE_ID=...
VAULT_SECRET_ID=...
VAULT_TRANSIT_MOUNT=transit
VAULT_TRANSIT_KEY=inventory
```

The Role ID, Secret ID, and Vault tokens are secrets or sensitive credentials.
They must never be committed.

`.env.example` may contain variable names and safe defaults, but not real
credential values:

```dotenv
VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
VAULT_TRANSIT_MOUNT=transit
VAULT_TRANSIT_KEY=inventory
# AppRole: set VAULT_ROLE_ID and VAULT_SECRET_ID in .env.local only
```

Continue using the existing mise/secret-loading workflow. Do not replace it
without an explicit request.

### 4. Error handling

Ensure a Vault `403` produces an actionable error that distinguishes it from
authentication failure. A useful message should identify:

- The denied Vault path.
- The AppRole name, when known.
- The policy name expected on the token.
- The capability required.
- The fact that an administrator must repair the server-side ACL.

For this operation, the message should effectively say:

```text
Vault denied transit/encrypt/inventory. AppRole authentication succeeded, but
the token requires update capability from the py-server-manage policy.
```

Never include the Vault token, Secret ID, or complete authentication response in
an exception or log entry.

### 5. Tests

Unit tests must mock Vault. They must not depend on the live server.

Cover at least:

- Successful AppRole login.
- AppRole response missing `auth.client_token`.
- Invalid or expired AppRole credentials.
- Successful Transit encryption.
- Successful Transit decryption.
- Base64 round trip for arbitrary bytes.
- Vault `403` mapped to an authorization-specific project error.
- Vault unavailable or timed out.
- Custom Transit mount and key names.
- No credential values written to logs.

The existing test location may remain:

```text
tests/unit/test_vault_transit.py
```

If the Vault integration becomes a package, this can later become:

```text
tests/unit/vault/
├── test_auth.py
├── test_client.py
└── test_transit.py
```

Only explicitly marked integration tests may contact the real Vault server.

### 6. Round-trip verification

Add or preserve a test that verifies:

```text
plaintext bytes
    → Base64
    → Vault Transit encrypt
    → ciphertext
    → Vault Transit decrypt
    → Base64 decode
    → identical plaintext bytes
```

For manual testing, use a temporary output rather than overwriting the original:

```bash
mise run cli -- inventory decrypt \
  data/tailscale-api-nodes.yaml.enc \
  --output /tmp/tailscale-api-nodes.decrypted.yaml

diff -u \
  data/tailscale-api-nodes.yaml \
  /tmp/tailscale-api-nodes.decrypted.yaml
```

No `diff` output means the round trip is exact.

Confirm the actual CLI syntax before changing documentation; preserve the
working command interface if it differs from this example.

### 7. Git handling

Plaintext inventory output must remain ignored:

```gitignore
data/*
```

If encrypted inventories are intended to be committed, add deliberate
exceptions rather than broadly tracking everything under `data/`:

```gitignore
data/*
!data/.gitkeep
!data/*.enc
```

Do not change this policy automatically. First confirm whether encrypted
inventories are intended for the public repository. Transit ciphertext hides
the plaintext, but filenames and repository history can still reveal metadata.

Never commit:

- `.env.local`
- `VAULT_TOKEN`
- `VAULT_ROLE_ID`
- `VAULT_SECRET_ID`
- Authentik client secrets
- Decrypted inventory files
- Captured Vault API responses containing tokens

## Documentation corrections

Update `docs/VAULT.md` so it records the observed failure and final resolution:

1. AppRole login can succeed while Transit remains unauthorized.
2. `vault token capabilities transit/encrypt/inventory` originally returned
   `deny`.
3. The `py-server-manage` ACL policy was absent and had to be created using a
   root/admin token.
4. The policy grants `update` on the Transit encrypt and decrypt endpoints.
5. A fresh AppRole capability check returned `update`.
6. The `serverops inventory encrypt` command subsequently succeeded.

Do not put credentials, token IDs, token accessors, Secret IDs, or Authentik
client secrets in the documentation.

Also correct any instructions implying:

```bash
vault policy write py-server-manage - <<'EOF'
# keep any existing rules...
EOF
```

is safe for an existing policy. `vault policy write` replaces the complete
policy. For an existing policy, an administrator must first export it, edit the
complete HCL, and write it back.

## OIDC policy status

The Authentik OIDC role is named `inventory`. A successful OIDC token showed:

```text
policies: [default inventory]
```

At the time of troubleshooting, only the root policy was found when inspecting
Vault ACL policies. Do not assume the human `inventory` ACL policy is correctly
defined merely because its name appears on the token.

This did not block the AppRole repair because the root token was used. Treat the
design of human `inventory` and separate `vault-admin` policies as future
server-administration work. Do not grant policy-administration capabilities to
the normal `inventory` role as part of application development.

## Root-token handling

The root token was used only to repair server configuration.

The IDE must never:

- Read `~/.vault-token`.
- Print a token lookup's `id` field.
- Copy tokens into diagnostics or fixtures.
- Revoke the initial root token automatically.
- Store the root token in project configuration.

After administrative work, the operator should clear the local root session
without revoking the root token:

```bash
rm -f ~/.vault-token
unset VAULT_TOKEN
vault login -method=oidc role=inventory
```

Root-token lifecycle decisions remain manual administrative operations.

## External dotfiles helper module

A separate `hashicorp-vault` shell module was prepared for the dotfiles
repository. It includes:

- OIDC login
- AppRole login
- Transit encryption/decryption for files and stdin
- KV v2 helpers
- token inspection/logout
- response unwrapping

That module is not part of `py-server-manage`. Do not copy its shell
implementation into the Python package. The Python project should continue
using `hvac`; the shell module is for interactive operator convenience.

## Definition of done

The IDE task is complete when:

- Existing working encryption remains functional.
- `hvac` is the sole Python Vault client.
- Authentication and authorization failures are distinguished.
- Transit operations are covered by mocked unit tests.
- No credentials can be logged or committed.
- `docs/VAULT.md` reflects the real policy failure and repair.
- The plaintext/encrypted inventory Git policy is documented and intentional.
- The live Vault server is not modified by automated tests.

