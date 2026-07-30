# Diagnostics Agent Instructions

## Scope

These instructions apply to diagnostics code and documentation in this
directory and its subdirectories.

This module investigates failures across the user's server-management stack,
including:

- Coolify applications, services, deployments, proxy configuration, and health
  checks
- Docker containers, Compose projects, networks, volumes, images, logs, and
  resource use
- Cloudflare DNS, proxying, TLS, tunnels, redirects, and origin connectivity
- Tailscale nodes, DNS, routes, ACL-related symptoms, sidecars, and service
  reachability
- Host networking, ports, firewalls, systemd services, storage, memory, CPU,
  permissions, and filesystem ownership
- HashiCorp Vault connectivity, authentication, policies, capabilities, Agent
  templates, and Transit operations
- Application configuration, environment injection, databases, reverse
  proxies, and upstream dependencies

The diagnostics module must identify and explain problems. It must not silently
become a repair or deployment system.

## Core Diagnostic Method

Use an evidence-first, read-only-first workflow:

1. Define the reported symptom precisely.
2. Identify the target environment and host.
3. Map the complete request or dependency path.
4. Test each boundary from the outside inward.
5. Gather timestamped evidence using the least privileged command available.
6. Separate observations from interpretations.
7. Rank likely causes by evidence and impact.
8. propose safe verification steps.
9. Require explicit approval before making any change.
10. Verify the original symptom again after an approved repair.

For an HTTP failure, reason through the path explicitly:

```text
client
  -> DNS
  -> Cloudflare or Tailscale
  -> host firewall and listening port
  -> Coolify proxy
  -> Docker network
  -> container
  -> application
  -> database or other dependency
```

Do not jump directly to the application container when an earlier boundary has
not been tested.

## Target Identification

Before running a remote, privileged, Docker, Coolify, Vault, or destructive
command, establish:

- whether the target is the local development machine or a remote server
- the intended hostname or inventory identifier
- whether the environment is development, staging, or production
- whether the command is read-only or mutating
- whether sudo or elevated credentials are actually required

Never infer the target host from the current shell prompt alone. If the target
is ambiguous and the command could mutate state, stop and ask.

Diagnostic reports and structured output should include the target identifier,
collection time, tool version where relevant, and whether collection was local
or remote.

## Safety Boundary

Diagnostics are read-only by default.

Allowed without repair authorization:

- reading configuration with secrets redacted
- checking process, container, service, network, DNS, TLS, and filesystem state
- inspecting logs with bounded time or line limits
- querying health endpoints
- checking Vault token capabilities without exposing the token
- generating a report or proposed remediation

The following are repairs and require explicit user authorization:

- restarting, stopping, recreating, or removing a service or container
- redeploying a Coolify resource
- changing DNS, TLS, proxy, firewall, routing, or Tailscale configuration
- modifying Compose files, environment variables, systemd units, ownership, or
  permissions
- writing Vault policies, roles, auth configuration, or secrets
- pruning Docker resources
- deleting logs, caches, volumes, databases, backups, or deployment files
- installing or upgrading packages

Never use a repair as a diagnostic test when a non-mutating test can provide the
same evidence.

Never disable TLS verification, authentication, a firewall, an ACL, or another
security control merely to make a failing request succeed.

## Destructive Operations

Never automatically execute:

- `docker system prune`, `docker volume prune`, or equivalent cleanup
- `docker compose down -v`
- broad recursive `rm`, `chmod`, `chown`, or `setfacl`
- database drop, truncate, restore, or schema migration commands
- `git reset --hard`, forced checkout, history rewriting, or force-push
- Vault secret deletion, token revocation, auth-method disablement, or policy
  removal
- Coolify resource deletion
- firewall flushes or broad allow rules

If one of these is genuinely required, explain:

1. why it is necessary
2. the exact target
3. the expected effect
4. the rollback or recovery path
5. what data could be lost

Then wait for explicit approval.

## Secrets and Redaction

Treat all credentials and decrypted configuration as sensitive.

Never print, persist in reports, or commit:

- Vault tokens, AppRole Secret IDs, wrapped tokens, or unseal material
- API tokens for Coolify, Tailscale, Cloudflare, GitHub, or other services
- private keys, passwords, cookies, bearer tokens, or session data
- complete `.env` files
- database connection strings containing credentials
- decrypted inventory files

Commands and code must avoid leaking secrets through:

- command-line arguments visible in process listings
- shell tracing
- exception messages
- debug logs
- captured environment dumps
- generated Markdown, YAML, or JSON reports
- subprocess stdout and stderr

Use allowlisted fields when collecting environment or configuration data.
Redact sensitive values structurally rather than relying only on string
replacement after collection.

Do not read secret values when metadata, a capability check, a checksum, or the
presence of a key is sufficient.

## Command Execution

Prefer stable, machine-readable output:

- JSON or YAML from supported CLIs
- explicit formatting flags
- bounded log queries such as `--since`, `--until`, or `--tail`
- explicit resource names and paths
- commands that are safe to run repeatedly

Avoid:

- parsing decorative terminal tables when structured output exists
- unbounded `journalctl`, Docker logs, or recursive filesystem scans
- shell pipelines assembled from untrusted values
- `shell=True` in Python
- interpolating hostnames, paths, container names, or user input into shell
  strings

Python subprocess calls should use argument arrays, timeouts, captured output,
and explicit error handling. Validate external identifiers before passing them
to a CLI.

Every diagnostic command should have a reasonable timeout. A timed-out command
is evidence and must not cause the whole diagnostic run to hang indefinitely.

## Logs

Collect only the smallest useful log window.

Reports should retain:

- log source
- relevant timestamp range
- timezone when known
- container or service identifier
- a short redacted excerpt or a structured summary

Do not copy entire production logs into the repository. Prefer summarizing
repeated messages with counts while preserving representative examples.

Correlate timestamps across Cloudflare, the host, Coolify, Docker, and the
application before claiming that events are related.

## Diagnostic Findings

Use these evidence labels consistently:

- **Observed:** Directly supported by command output, logs, configuration, or a
  reproducible request.
- **Inferred:** The most likely explanation derived from observations.
- **Unverified:** Plausible, but the required evidence has not been collected.
- **Ruled out:** Tested and shown not to explain the symptom.

Do not present an inference as a confirmed root cause.

Rank possible causes using:

- strength of supporting evidence
- position in the failing request path
- likelihood
- blast radius
- reversibility of the proposed test or repair

## Required Report Format

Diagnostics should produce a concise human-readable summary and, when useful, a
structured artifact.

Use this order:

1. **Symptom**
2. **Target and environment**
3. **Collection time**
4. **Request or dependency path**
5. **Observed evidence**
6. **Ruled-out causes**
7. **Likely causes, ranked**
8. **Missing evidence**
9. **Safe next checks**
10. **Proposed remediation**
11. **Risks and rollback**
12. **Post-repair verification**

When no root cause is proven, say so plainly.

Exit codes for diagnostic CLI commands must distinguish:

- completed with no issue detected
- issue detected and reported
- incomplete because prerequisites or access were unavailable
- internal diagnostic failure

Document the chosen numeric codes in the CLI help and tests.

## Domain-Specific Guidance

### HTTP 502, 503, and 504

Check, in order:

1. public and tailnet DNS resolution
2. TCP and TLS reachability
3. Cloudflare proxy, tunnel, and SSL-mode behavior
4. origin listener and firewall state
5. Coolify proxy health, routes, and target port
6. container state, health check, restart count, and logs
7. Docker network membership and name resolution
8. application listener address and port
9. upstream database, cache, queue, or API dependencies

Differentiate:

- 502: invalid or unavailable upstream response
- 503: unavailable service or intentionally unavailable backend
- 504: upstream response timeout

Treat these as starting hypotheses, not proof of the failing component.

### Docker and Compose

Inspect before changing:

- `docker ps` and container health
- restart counts and exit codes
- bounded logs
- `docker inspect`
- Compose-resolved configuration
- network membership
- published and exposed ports
- mounts and volume presence
- image identity
- CPU, memory, PID, and disk pressure

Do not assume a container is healthy merely because it is running.
Do not expose a new host port as a shortcut when proxy or Docker networking is
the intended path.

### Coolify

Prefer the Coolify API or CLI and documented resource identifiers over editing
files managed under Coolify's data directories.

Correlate:

- project, environment, application, service, and deployment UUIDs
- proxy configuration
- deployment status and logs
- generated Compose configuration
- container labels and networks

Do not edit generated deployment files directly unless the user explicitly
requests that approach and understands the change may be overwritten.

### Tailscale

Distinguish:

- node connectivity
- MagicDNS resolution
- subnet routing
- exit-node behavior
- ACL or grants behavior
- sidecar namespace and shared-network behavior
- service listener binding

A successful Tailscale ping proves node-level reachability, not application
reachability.

### Vault

Check authentication and authorization separately.

Prefer:

- token metadata that does not reveal the token
- `vault token capabilities`
- auth mount and role existence
- policy-path comparison
- Vault Agent and template logs with redaction

Do not respond to a permission error by proposing a broad administrative policy.
Recommend the narrowest capability on the narrowest path required by the
application.

Never persist a short-lived Vault token into a generated `.env` file when Vault
Agent, response wrapping, or workload-specific authentication is appropriate.

## Implementation Standards

Diagnostics code must:

- keep collectors separate from analyzers and report renderers
- return typed structured results rather than preformatted terminal text
- record collection errors without discarding successful evidence
- use dependency injection or fixtures for external command execution
- support offline tests using saved, sanitized fixtures
- avoid requiring production credentials during tests
- maintain deterministic output apart from explicit timestamps
- degrade gracefully when a CLI or permission is unavailable

Suggested separation:

```text
diagnostics/
  collectors/
  analyzers/
  checks/
  models/
  renderers/
  fixtures/
```

Do not add a new abstraction unless it supports at least one concrete
diagnostic workflow and improves testability or safety.

## Testing Requirements

For every new diagnostic check, test:

- healthy state
- expected failure state
- malformed or partial command output
- command not installed
- permission denied
- timeout
- remote host unreachable
- secret redaction
- deterministic report rendering

Tests must not connect to the live Coolify server, tailnet, Vault instance,
Cloudflare account, or production database by default.

Integration tests requiring external systems must be explicitly marked and
opted into using environment variables or test configuration.

## Completion Criteria

Before declaring a diagnostics change complete:

1. Run the relevant unit tests.
2. Run the repository formatter, linter, and type checker.
3. Confirm failure paths and timeouts are covered.
4. Confirm fixtures contain no real credentials or identifying production data.
5. Confirm reports redact secrets.
6. Confirm no repair behavior occurs without explicit authorization.
7. Update CLI help and user documentation when behavior or output changes.
8. Summarize what was verified and what remains unverified.

