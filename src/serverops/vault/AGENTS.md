# Vault Module Agent Instructions

## Scope

These instructions apply to `src/serverops/vault/` and its descendants. They
supplement the repository-root `AGENTS.md`; follow both, with this file taking
precedence for Vault-specific work.

This module provides the security boundary between `serverops`, HashiCorp
Vault, and encrypted infrastructure inventory files. Treat changes here as
security-sensitive even when they appear mechanical.

## Purpose

The Vault module is responsible for:

- constructing correctly configured `hvac.Client` instances;
- authenticating unattended processes through AppRole;
- keeping Vault tokens in memory rather than persistent project files;
- reading explicitly authorized KV v2 secrets;
- encrypting and decrypting inventories through Vault Transit;
- exposing predictable, typed errors to the CLI layer;
- preserving ciphertext and plaintext file integrity during file operations.

It is not responsible for:

- collecting Coolify or Tailscale inventory data;
- formatting dashboards or reports;
- configuring Authentik/OIDC;
- administering Vault mounts, keys, roles, or policies during normal runtime;
- embedding production credentials into generated files.

## Expected Module Boundaries

Keep responsibilities separated:

| File | Responsibility |
| --- | --- |
| `client.py` | Parse client connection settings and construct `hvac.Client`. Do not perform AppRole login or Transit operations here. |
| `auth.py` | AppRole login, token assignment, and authentication validation. |
| `transit.py` | Base64 conversion and Vault Transit encrypt/decrypt operations. |
| `errors.py` | Project-specific Vault exceptions and safe error translation. |
| `config.py` | Vault-specific configuration objects, only if configuration has outgrown `client.py`. |
| CLI integration | Parse arguments and present results; delegate cryptographic work to this module. |

Do not combine these layers merely to reduce file count. Avoid parallel Vault
implementations under `serverops.utils`; migrate callers deliberately if legacy
code still exists.

## Current Configuration Contract

Support the existing environment and production bootstrap contract:

```text
VAULT_ADDR
VAULT_ROLE_ID
VAULT_SECRET_ID
VAULT_ROLE_ID_FILE
VAULT_SECRET_ID_FILE
VAULT_TOKEN
VAULT_NAMESPACE
VAULT_CACERT
VAULT_CLIENT_CERT
VAULT_CLIENT_KEY
VAULT_SKIP_VERIFY
VAULT_TRANSIT_MOUNT
VAULT_TRANSIT_KEY
VAULT_KV_MOUNT
VAULT_KV_PATH
VAULT_APPROLE_MOUNT
VAULT_APPROLE_NAME
```

Current defaults are:

```text
VAULT_ADDR=https://vault.tiger-bushmaster.ts.net
VAULT_TRANSIT_MOUNT=transit
VAULT_TRANSIT_KEY=inventory
VAULT_KV_MOUNT=secret
VAULT_APPROLE_MOUNT=approle
VAULT_APPROLE_NAME=py-server-manage
```

Do not hardcode real RoleIDs, SecretIDs, Vault tokens, Tailscale credentials,
Coolify tokens, or client secrets. Public example files may contain variable
names and safe placeholder values only.

For production, prefer bootstrap credentials stored outside the repository:

```text
/etc/serverops/credentials/vault-role-id
/etc/serverops/credentials/vault-secret-id
```

The intended production KV path is:

```text
secret/data/py-server-manage/prod
```

File-based credentials take precedence over environment values when the
production configuration explicitly supplies `*_FILE`. Reject ambiguous,
unreadable, empty, or overly permissive credential files with a safe error.

## Authentication Rules

- Use Authentik OIDC for interactive human CLI/UI sessions.
- Use AppRole for `py-server-manage` and other unattended workloads.
- Never automate with a human OIDC token.
- Never use a Vault root token in application code, tests, examples, or CI.
- Exchange RoleID and SecretID for a short-lived token and retain that token in
  memory only.
- Do not write application tokens to `.env`, logs, cache files, test snapshots,
  or generated inventories.
- Treat SecretID as a password. RoleID is not sufficient for authentication but
  should still not be needlessly exposed.
- `client.is_authenticated()` proves token validity only; it does not prove
  permission to use a particular Transit or KV path.
- Preserve least-privilege AppRole behavior. The application should normally
  encrypt inventories but should receive decryption access only when required.

The current AppRole design uses short-lived credentials:

```text
role name: py-server-manage
token type: batch
token TTL: 15 minutes
token maximum TTL: 30 minutes
SecretID TTL: 24 hours
SecretID uses: 10
```

Do not silently broaden these values or policies.

## Transit Rules

The inventory key is:

```text
transit/keys/inventory
```

The corresponding authorization paths are:

```text
transit/encrypt/inventory
transit/decrypt/inventory
```

Both operations use the Vault `update` capability.

When changing Transit code:

- use Vault Transit rather than implementing local cryptography;
- Base64-encode plaintext bytes exactly once before calling Vault;
- decode returned plaintext exactly once after decryption;
- preserve bytes without newline, encoding, or normalization surprises;
- support arbitrary file bytes unless the public CLI explicitly limits formats;
- treat `vault:vN:` ciphertext as opaque;
- do not parse, truncate, normalize, or reconstruct Vault ciphertext;
- preserve the current `.enc` file format and compatibility unless a migration
  is explicitly requested;
- add versioned envelope metadata before changing any persisted format;
- never overwrite the source plaintext by default;
- write output atomically through a temporary file in the destination directory;
- clean up temporary plaintext and partial output on failure;
- avoid loading unnecessarily large files multiple times.

The established CLI behavior includes:

```bash
mise run cli -- inventory encrypt data/tailscale-api-nodes.yaml
```

which produces:

```text
data/tailscale-api-nodes.yaml.enc
```

Decrypt operations should require an explicit safe output destination and must
not accidentally commit decrypted inventories.

## KV v2 Rules

- Use the KV v2 API for paths beneath the configured `VAULT_KV_MOUNT`.
- Keep the mount name separate from the secret path.
- Do not include `data/` twice when using `hvac` KV v2 helpers.
- Retrieve only the specific path required by the command.
- Do not enumerate secrets unless the feature explicitly requires listing.
- Return narrowly scoped configuration values rather than propagating the full
  secret response throughout the application.
- Do not persist a generated `.env.prod` containing the complete secret set.
  Production applications should retrieve required values at runtime.

## TLS and Networking

- Keep TLS verification enabled.
- Support `VAULT_CACERT` for a private certificate authority.
- Support `VAULT_CLIENT_CERT` and `VAULT_CLIENT_KEY` as a pair when mutual TLS
  is deliberately configured.
- Never set `VAULT_SKIP_VERIFY=true` in committed configuration, examples, or
  tests intended to model production.
- Reject malformed `VAULT_ADDR` values early.
- Do not replace the tailnet Vault hostname with a loopback or container-local
  address unless the deployment architecture specifically requires it.
- Do not assume tailnet transport removes the need for TLS identity validation.

## Error Handling

Translate library and HTTP failures into typed project exceptions at the module
boundary. Preserve enough context to diagnose the operation, mount, and key,
but never include:

- Vault tokens;
- SecretIDs;
- passwords or client secrets;
- plaintext inventory contents;
- complete KV secret responses;
- sensitive environment-variable values.

Differentiate at least:

- invalid or missing local configuration;
- authentication failure;
- permission denied;
- Vault unavailable or TLS failure;
- missing mount/key/path;
- malformed Vault response;
- encryption/decryption failure;
- invalid ciphertext;
- unsafe file operation.

Use exception chaining (`raise ... from exc`) so debug traces retain the
original cause without exposing secrets in the user-facing message.

## Coding Standards

- Target Python 3.12.
- Use modern type annotations and precise return types.
- Use `pathlib.Path` for filesystem paths.
- Prefer immutable, slotted dataclasses for configuration values.
- Keep functions small and dependency injection straightforward.
- Accept an existing `hvac.Client` in lower-level services where practical so
  unit tests do not need network access.
- Avoid global mutable clients and module-import side effects.
- Do not read credentials or contact Vault at import time.
- Document security-relevant behavior, side effects, and exceptions.
- Do not add explanatory comments that merely restate the code.
- Preserve Typer `Annotated` metadata and CLI signatures when touching command
  integration.

## Testing Rules

Tests must not require the real Vault instance by default.

- Unit-test request construction and response handling with mocked/fake clients.
- Include tests for missing credentials, empty credential files, invalid URLs,
  bad booleans, permission errors, malformed responses, invalid Base64, and
  atomic-write cleanup.
- Verify that exceptions and logs do not contain supplied test secrets.
- Round-trip arbitrary bytes through mocked Transit responses.
- Test the difference between authentication success and capability failure.
- Keep a real-Vault integration test behind an explicit opt-in marker or
  environment flag.
- Never use production RoleID, SecretID, tokens, endpoints, or ciphertext in
  fixtures.

Before selecting commands, inspect `pyproject.toml` and the repository-root
`AGENTS.md`. Typical verification is:

```bash
uv run ruff check src/serverops/vault tests
uv run pytest
```

If configured in the project, also run:

```bash
uv run mypy src/serverops/vault
```

For CLI-affecting changes, verify help and a non-destructive command:

```bash
mise run cli -- inventory --help
```

Never run a live encrypt/decrypt operation merely as a routine unit test. If a
live verification is necessary, state the exact target and obtain authorization
before invoking it.

## Agent Workflow

Before editing:

1. Read the repository-root `AGENTS.md`, this file, and relevant tests.
2. Inspect current callers before changing public symbols or file formats.
3. Check `git status` and preserve unrelated user changes.
4. Identify whether the task is client construction, authentication, Transit,
   KV retrieval, CLI presentation, or deployment configuration.
5. Confirm that the proposed change stays within that layer.

While editing:

1. Make the smallest coherent change.
2. Preserve existing APIs unless migration was requested.
3. Add or update tests alongside behavior changes.
4. Keep secrets out of source, commands, logs, fixtures, patches, and output.
5. Do not change live Vault configuration, policies, roles, mounts, or keys
   unless the user explicitly requests that external mutation.

Before finishing:

1. Run focused tests and static checks.
2. Review the diff for secret material and accidental format changes.
3. Confirm no plaintext inventory or `.env` file was added.
4. Report changed files, verification performed, and any unverified live-Vault
   assumption.

## Prohibited Actions

Do not:

- commit `.env`, `.env.prod`, `.vault-token`, RoleID, SecretID, or Vault token;
- print credentials for debugging;
- weaken TLS verification to make an error disappear;
- introduce a second encryption implementation;
- reuse the unrelated `transit/keys/user-data` key for inventories;
- delete, rotate, export, or reconfigure Vault keys without explicit approval;
- grant the application broad paths such as `transit/*` or `secret/data/*`;
- silently add decryption permission to an encrypt-only workload;
- mutate live Vault state from unit tests;
- use destructive Git commands to recover from an agent mistake;
- overwrite user files or unrelated dirty-worktree changes.

When uncertain, stop and request clarification before expanding permissions,
changing ciphertext formats, or altering production authentication.
