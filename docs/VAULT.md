# HashiCorp Vault Authentication

This document describes the two authentication methods configured for this
environment:

- **OIDC through Authentik** for interactive human access.
- **AppRole** for `py-server-manage` and other non-interactive automation.

These methods deliberately separate human identity from machine identity.
People log in through Authentik and receive a Vault token based on their user or
group membership. Applications exchange a Vault AppRole `role_id` and
short-lived `secret_id` for a narrowly scoped token.

## Environment

| Setting | Value |
| --- | --- |
| Vault address | `https://vault.tiger-bushmaster.ts.net` |
| Vault version at setup | `1.17.6` |
| Storage backend | Integrated Storage (Raft) |
| HA state at setup | Active |
| OIDC identity provider | Authentik |
| Authentik application slug | `vault` |
| Authentik provider | `Provider for hashicorp Vault` |
| Vault OIDC role | `inventory` |
| Application AppRole | `py-server-manage` |

Set the Vault address before using the CLI:

```bash
export VAULT_ADDR="https://vault.tiger-bushmaster.ts.net"
vault status
```

The server should report `Sealed: false`. Do not continue with authentication
troubleshooting if Vault is sealed or unreachable.

## Authentication design

| Actor | Authentication | Typical use |
| --- | --- | --- |
| Administrator or developer | Authentik OIDC | Interactive CLI and UI access |
| `py-server-manage` | AppRole | Inventory collection and automated jobs |
| CI/CD job | A dedicated AppRole | Non-interactive deployment or scheduled work |

Do not give an application a human OIDC token. Do not give a person an
application's `secret_id`. Each application should eventually receive its own
AppRole and least-privilege policy.

## OIDC authentication through Authentik

### Purpose

OIDC lets a user authenticate to Vault with their Authentik account. Vault
redirects the browser to Authentik, Authentik verifies the user and any bound
policies, and Vault exchanges the returned authorization code for a Vault token.

The Authentik application uses:

- Slug: `vault`
- Provider: `Provider for hashicorp Vault`
- Provider type: OAuth2/OpenID Connect
- Client type: Confidential
- Policy engine mode: `ANY`

Because this is a confidential client, the Authentik client secret must match
the `oidc_client_secret` stored in Vault. Whether Vault is only reachable inside
the tailnet does not change the client type.

### Vault OIDC configuration

The OIDC auth method is mounted at `auth/oidc`. Inspect the live configuration
without displaying the client secret:

```bash
vault auth list
vault read auth/oidc/config
vault read auth/oidc/role/inventory
```

The role was created with these important settings:

```text
role_type          = oidc
user_claim         = sub
bound_audiences    = <AUTHENTIK_CLIENT_ID>
allowed_redirect_uris includes:
  http://localhost:8250/oidc/callback
```

`bound_audiences` must exactly match the Authentik client ID. The local callback
is used by `vault login -method=oidc`, whose CLI listener runs on port `8250`.

The complete live configuration is authoritative. It can be exported safely
for review with:

```bash
vault read -format=json auth/oidc/role/inventory |
  jq '.data | del(.oidc_client_secret)'
```

### Interactive login

```bash
export VAULT_ADDR="https://vault.tiger-bushmaster.ts.net"
vault login -method=oidc role=inventory
```

Vault prints an Authentik authorization URL and normally opens it in the
browser. After authentication, Authentik redirects to the local callback and
the CLI stores the resulting Vault token in `~/.vault-token`.

Verify the token:

```bash
vault token lookup
vault token capabilities secret/data/py-server-manage/example
```

Avoid exporting a long-lived Vault token into shell startup files.

### Authentik access policy

Authentik policies bound to the Vault application decide who may reach the OIDC
provider. A policy limited to the `developers` group will deny `akadmin` unless
that account is also a member of the group.

The preferred arrangement is:

1. Use an ordinary named administrator/developer account for daily access.
2. Put that account in the appropriate Authentik group.
3. Keep `akadmin` as a recovery/bootstrap account.
4. If emergency access for `akadmin` is required, bind a separate explicit
   administrator policy rather than weakening the developer policy.

Reset a forgotten Authentik user's password from:

```text
Admin interface → Directory → Users → <user> → Set password
```

### OIDC troubleshooting

#### `No value found at auth/oidc/role`

This command attempts to list a path that is not listable:

```bash
vault list auth/oidc/role
```

Read the known role directly:

```bash
vault read auth/oidc/role/inventory
```

The Vault CLI may also show roles through the API if the current token has
sufficient access, but the direct read is the reliable check.

#### Authentik says `Policy binding ... returned result False`

The logged-in user did not satisfy an Authentik policy bound to the Vault
application. Check:

- Which Authentik account is currently logged in.
- The user's group membership.
- Policies bound to the `vault` application/provider.
- Whether policy engine mode `ANY` has the intended behavior.

#### `invalid_client` during the code exchange

This means Authentik rejected Vault as an OAuth client. It is not a Vault policy
or user-group error. Check:

1. Authentik provider client type is **Confidential**.
2. Vault's `oidc_client_id` exactly matches Authentik's client ID.
3. Vault's `oidc_client_secret` is the current Authentik secret.
4. The OIDC discovery URL belongs to the `vault` provider, including its
   required trailing slash.
5. The callback URI is allowed in Authentik.

If the Authentik client secret was regenerated, update Vault:

```bash
read -rsp "Authentik client secret: " AUTHENTIK_CLIENT_SECRET
printf '\n'

vault write auth/oidc/config \
  oidc_discovery_url="<AUTHENTIK_VAULT_ISSUER_URL>" \
  oidc_client_id="<AUTHENTIK_CLIENT_ID>" \
  oidc_client_secret="$AUTHENTIK_CLIENT_SECRET" \
  default_role="inventory"

unset AUTHENTIK_CLIENT_SECRET
```

Do not place the client secret in shell history, Git, `VAULT.md`, Compose files,
or inventory output.

#### Redirect or callback failure

For CLI login, both Vault and Authentik must allow:

```text
http://localhost:8250/oidc/callback
```

The callback points to the computer running the Vault CLI—not the Vault server.
If logging into the Vault web UI is also required, add the UI callback shown by
Vault to both the Vault role and Authentik provider without removing the CLI
callback.

## AppRole authentication

### Purpose

AppRole is intended for applications, scripts, scheduled jobs, and containers.
It does not open a browser. The application authenticates with:

- `role_id`: a stable identifier for the AppRole.
- `secret_id`: a sensitive, preferably short-lived credential.

Vault returns a temporary token carrying only the policies assigned to that
AppRole.

For this environment, the application role is:

```text
py-server-manage
```

Its intended token controls are:

```text
token_type         = batch
token_ttl          = 15m
token_max_ttl      = 30m
secret_id_ttl      = 24h
secret_id_num_uses = 10
```

Batch tokens are suitable for short automated jobs and create less storage
overhead than service tokens. They cannot be renewed, so the application should
authenticate again when it needs another token.

### Enable and inspect AppRole

AppRole only needs to be enabled once:

```bash
vault auth list
vault auth enable approle
```

If `approle/` is already in `vault auth list`, do not enable it again.

Inspect the configured role:

```bash
vault read auth/approle/role/py-server-manage
vault read auth/approle/role/py-server-manage/role-id
```

The role ID is not treated like a password, but it should not be unnecessarily
published. The Secret ID is confidential.

### Application policy

The role is intended to use a narrowly scoped policy for inventory operations.
The relevant paths are:

```hcl
# Encrypt inventory data using the inventory Transit key.
path "transit/encrypt/inventory" {
  capabilities = ["update"]
}

# Decrypt inventory data when the application genuinely needs plaintext.
path "transit/decrypt/inventory" {
  capabilities = ["update"]
}

# Read and write py-server-manage secrets in KV v2.
path "secret/data/py-server-manage/*" {
  capabilities = ["create", "read", "update", "delete"]
}

# List KV v2 metadata when inventory/discovery requires it.
path "secret/metadata/py-server-manage/*" {
  capabilities = ["list"]
}
```

The Transit paths allow Vault to perform encryption or decryption. The
application sends data to Vault but Vault does not store the ciphertext unless
the application separately stores it. KV v2 stores versioned secret values.

If the application only encrypts inventories and never decrypts them, remove
`transit/decrypt/inventory`. If it only uses Transit and not KV, remove the
`secret/...` rules. Least privilege is preferable to keeping unused access.

Inspect the actual policy attached to the role:

```bash
vault read -field=token_policies auth/approle/role/py-server-manage
vault policy read <POLICY_NAME>
```

### Authentication versus authorization (observed failure)

AppRole login can succeed while Transit encryption still fails with HTTP 403
`permission denied`. That is an **authorization** problem, not an application
bug.

Observed sequence during initial setup:

1. `serverops inventory encrypt` called `transit/encrypt/inventory`.
2. AppRole login returned a batch token whose policy **names** included
   `py-server-manage` and `default`.
3. `vault token capabilities transit/encrypt/inventory` returned **`deny`**.
4. Root cause: the ACL policy document named `py-server-manage` **did not exist**
   on the server. A policy name on a token does not grant capabilities until the
   matching ACL policy is defined.
5. After an administrator created the `py-server-manage` policy (Transit
   `update` on encrypt and decrypt paths), a fresh AppRole check returned
   **`update`** and `serverops inventory encrypt` succeeded without changing
   application code or `.env.local`.

The Python client distinguishes authentication failures from ACL denials; a 403
on Transit surfaces an error that names the denied path and the expected
`py-server-manage` policy.

**Creating or editing policies:** `vault policy write <name>` **replaces** the
entire policy document. For an existing policy, export with `vault policy read`,
edit the complete HCL, and write it back. Do not append with a partial heredoc
that omits existing rules.

The application must **not** create or repair ACL policies at startup. The
AppRole must not administer its own policies.

### Configure the AppRole

The following command represents the intended role settings. Use the policy
name shown by the inspection command above:

```bash
vault write auth/approle/role/py-server-manage \
  token_policies="<POLICY_NAME>" \
  token_type="batch" \
  token_ttl="15m" \
  token_max_ttl="30m" \
  secret_id_ttl="24h" \
  secret_id_num_uses=10
```

### Obtain credentials

Retrieve the stable role ID:

```bash
vault read -field=role_id \
  auth/approle/role/py-server-manage/role-id
```

Generate a new Secret ID:

```bash
vault write -field=secret_id -f \
  auth/approle/role/py-server-manage/secret-id
```

Creating a Secret ID requires an administrative or provisioning token. The
application itself should not have permission to mint unlimited Secret IDs.

For stronger delivery, use a response-wrapped Secret ID:

```bash
vault write -wrap-ttl=5m -f \
  auth/approle/role/py-server-manage/secret-id
```

The receiving process unwraps the one-time wrapping token:

```bash
vault unwrap -field=secret_id
```

### Log in with AppRole

Avoid putting credentials directly on a command line because they can leak
through shell history or process inspection:

```bash
read -r -p "Role ID: " VAULT_ROLE_ID
read -r -s -p "Secret ID: " VAULT_SECRET_ID
printf '\n'

VAULT_TOKEN="$(
  vault write -format=json auth/approle/login \
    role_id="$VAULT_ROLE_ID" \
    secret_id="$VAULT_SECRET_ID" |
  jq -r '.auth.client_token'
)"

export VAULT_TOKEN
unset VAULT_ROLE_ID VAULT_SECRET_ID
vault token lookup
```

An application can make the equivalent API request:

```http
POST /v1/auth/approle/login
Content-Type: application/json

{
  "role_id": "...",
  "secret_id": "..."
}
```

The response's `auth.client_token` is used as the `X-Vault-Token` header for
subsequent requests.

### Supplying AppRole credentials to `py-server-manage`

Preferred approaches, from strongest to weakest:

1. Deliver a short-lived response-wrapping token and unwrap it once at runtime.
2. Inject `role_id` and `secret_id` as protected runtime secrets.
3. Mount root-readable credential files into the container or systemd service.
4. Use environment variables only when the runtime protects them adequately.

Do not:

- Commit a `role_id`, `secret_id`, Vault token, or Authentik client secret.
- Write credentials into generated Coolify or Tailscale inventories.
- Bake credentials into a container image.
- Print credentials in CI logs or diagnostic output.
- Reuse the same AppRole across unrelated applications.

The application should authenticate only when needed, keep the returned token
in memory, and discard it when the inventory operation finishes.

`serverops` inventory encrypt/decrypt commands use the same AppRole flow via
the [`hvac`](https://github.com/hvac/hvac) Python client in `serverops.vault`:
set `VAULT_ADDR` and either `VAULT_TOKEN` or `VAULT_ROLE_ID` / `VAULT_SECRET_ID`
(or the matching CLI flags). See [Inventory Security](inventory-security.md) for Transit usage.

## OIDC versus AppRole

| Property | OIDC | AppRole |
| --- | --- | --- |
| Identity | Human Authentik user | Application or job |
| Browser required | Yes | No |
| Primary credentials | Authentik session | Role ID and Secret ID |
| Vault result | Scoped token | Scoped token |
| Recommended lifetime | Short interactive session | Very short batch token |
| Revocation point | User/group, OIDC role, or token | Secret ID, AppRole, or token |
| Main role here | `inventory` | `py-server-manage` |

## Rotation and revocation

### Rotate an AppRole Secret ID

Generate a replacement, deploy it safely, verify the application, and then
destroy the old Secret ID accessor:

```bash
vault list auth/approle/role/py-server-manage/secret-id

vault write \
  auth/approle/role/py-server-manage/secret-id-accessor/destroy \
  secret_id_accessor="<OLD_ACCESSOR>"
```

Vault stores Secret ID accessors for management without revealing the original
Secret ID.

### Revoke AppRole access immediately

To stop new logins while preserving the configuration for inspection:

```bash
vault write auth/approle/role/py-server-manage \
  bind_secret_id=true \
  secret_id_num_uses=1 \
  secret_id_ttl=1s
```

For a complete removal:

```bash
vault delete auth/approle/role/py-server-manage
```

Deleting the role is destructive. Existing tokens may remain valid until their
short TTL expires unless explicitly revoked.

### Rotate the Authentik client secret

1. Generate a new secret in the Authentik provider.
2. Immediately update `auth/oidc/config` in Vault.
3. Test `vault login -method=oidc role=inventory`.
4. Remove any temporary shell variable holding the secret.

There will be a login interruption between steps 1 and 2, so keep an
administrative Vault token available during rotation.

## Administrative verification checklist

```bash
export VAULT_ADDR="https://vault.tiger-bushmaster.ts.net"

vault status
vault auth list

vault read auth/oidc/config
vault read auth/oidc/role/inventory

vault read auth/approle/role/py-server-manage
vault read auth/approle/role/py-server-manage/role-id

vault list sys/policies/acl
vault read sys/health
```

Confirm that:

- Vault is unsealed and active.
- `oidc/` and `approle/` are enabled.
- OIDC role `inventory` has the correct audience and callback URLs.
- Authentik's confidential client secret matches Vault.
- AppRole `py-server-manage` has short TTLs and only its required policies.
- No credentials appear in Git, inventory YAML, Compose files, or logs.

## Values intentionally excluded

This document does not contain:

- Authentik client secret.
- AppRole Secret ID.
- Vault root or administrative tokens.
- Application Vault tokens.

Where a command contains `<AUTHENTIK_CLIENT_ID>`,
`<AUTHENTIK_VAULT_ISSUER_URL>`, or `<POLICY_NAME>`, retrieve the live value from
Authentik or Vault. Do not replace the placeholder in a committed copy of this
document with a secret.
