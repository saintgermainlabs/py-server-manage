# AGENTS.md

This file defines the operating contract for coding agents working in the
`py-server-manage` repository.

## Mission

Build a safe, modular Python operations toolkit that can monitor, diagnose,
configure, and manage:

- The local workstation.
- Remote Ubuntu servers over SSH.
- Coolify-managed applications, services, databases, deployments, and nodes.
- Docker Compose and systemd deployments outside Coolify.
- Cloudflare-proxied domains.
- Tailscale connectivity.
- Backup status and restoration readiness.

The same codebase must run locally, on the managed server, and through a
restricted OpenClaw integration.

## Read before changing code

Before implementing a change:

1. Read this file completely.
2. Read `README.md`.
3. Inspect `pyproject.toml`, `mise.toml`, and the existing package tree.
4. Run `git status --short`.
5. Inspect existing tests related to the requested module.
6. Run the narrowest relevant existing tests before editing.

Do not assume the package name, CLI executable, configuration format, or module
layout from documentation alone. The repository is authoritative.

## Tool ownership

Use:

- Mise for Python, uv, and versioned external command-line tools.
- uv for Python dependencies, the virtual environment, and the lockfile.
- The Ubuntu package/service installation for Tailscale when it is already
  installed with an active `tailscaled` systemd service.
- Coolipy for supported Coolify API operations.
- Small direct HTTP calls only when Coolipy does not support a required endpoint
  or behavior.

Do not add a Python dependency merely because a similarly named system CLI
exists.

Dependency changes must use:

```bash
uv add PACKAGE
uv add --dev PACKAGE
uv remove PACKAGE
```

Do not manually edit dependency versions in `uv.lock`.

## Safety model

### Diagnostics are read-only

Commands named `doctor`, `check`, `status`, `inspect`, `list`, `show`, `logs`,
`inventory`, or `report` must not modify external state.

They must not:

- Restart or stop services.
- Deploy or redeploy applications.
- Modify Docker networks.
- Change DNS, firewall, proxy, or Tailscale settings.
- Write into Coolify deployment directories.
- Change Compose files.
- Delete, prune, or rotate data.

### Mutations are explicit

Every mutating workflow must:

1. Live under a clearly mutating verb such as `deploy`, `restart`, `update`,
   `rollback`, `configure`, or `delete`.
2. Produce a preview by default.
3. Require `--apply`.
4. Verify that mutations are allowed by configuration.
5. Identify the exact target and resource.
6. Record a secret-redacted audit entry.
7. Return a nonzero exit code if the result cannot be verified.

Never add a global `--force` option that bypasses all safeguards.

### No arbitrary shell surface

Do not expose commands such as:

```text
run COMMAND
shell COMMAND
exec STRING
```

Provider modules must request typed operations. Runners must receive an argument
array and use `shell=False`.

Bad:

```python
subprocess.run(f"ssh {host} docker logs {container}", shell=True)
```

Better:

```python
runner.run(["docker", "logs", "--tail", str(tail), container], target=target)
```

Validate every user-controlled hostname, container name, resource identifier,
path, port, count, and URL before execution.

## Secrets and privacy

Never print, log, persist, or include in exceptions:

- API tokens.
- Authorization or Cookie headers.
- Passwords.
- SSH private keys.
- Complete environment dumps.
- Coolify sensitive fields.
- Signed URLs.
- Database connection strings containing credentials.

All external data must pass through the shared redaction layer before:

- Console rendering.
- JSON serialization.
- Markdown report generation.
- Logging.
- Exception display.
- Storage in fixtures.

When uncertain whether a field is sensitive, redact it.

Tests involving secrets must use obviously fake values and assert that those
values do not appear in output.

## Configuration

Private runtime configuration belongs in:

```text
~/.config/py-server-manage/config.yaml
```

The repository may contain only a sanitized example:

```text
config/example.yaml
```

Do not introduce competing private configuration locations such as
`serverops/.config.yaml`.

Configuration precedence should remain predictable:

1. Explicit CLI option.
2. Environment variable.
3. User configuration file.
4. Safe application default.

Secrets should normally come from environment variables or an approved secret
provider, not YAML.

## Local and SSH targets

All host-side providers must work through the common runner abstraction.

Supported execution targets:

- `local`: run on the machine invoking the CLI.
- `ssh`: run on a named remote target through the user's SSH configuration.

Provider and diagnostic code must not care whether the selected runner is local
or SSH.

Do not:

- Disable SSH host-key checking.
- Automatically remove known-host entries.
- Copy private keys into the repository.
- Embed usernames, IP addresses, or ports in provider modules.
- Assume passwordless sudo.

If a check requires elevated privileges, report it as unavailable with a clear
explanation. Do not attempt to expand sudo permissions automatically.

## Provider boundaries

Keep external-system knowledge in feature modules under `src/serverops/`:

- `backup/`: host-level backup discovery and (later) Borg/systemd workflows.
- `tailscale/`: Tailscale CLI/API inventory and node parsing.
- `coolify/`: Coolify API client and inventory export.
- `diagnostics/`: host/Docker diagnostics (`debug/` remains a compatibility alias).
- `openclaw/`: OpenClaw skill helpers (skill files remain under `openclaw/`).
- `inventory/`: discovery adapters (`coolify`, `docker`, `system`) and dashboard transforms.
- `vault/`: HashiCorp Vault AppRole authentication and Transit helpers for inventory encryption.
- `utils/`: redaction, filesystem probes, command helpers (no Vault logic).
- `provision/`: future host bootstrap stubs.

Shared primitives stay at the package root:

- `runner.py`: local/SSH command execution.
- `config.py`, `paths.py`, `app_state.py`: shared contracts.
- `models/`: shared Pydantic models.

The root `cli.py` imports each module's Typer app and registers it. Diagnostics
orchestrate providers but should not duplicate their parsing logic.

Reporting formats typed results but should not perform probes.

## Proxy doctor contract

The proxy diagnostic module must examine failures from outside inward:

1. Input URL validation.
2. DNS resolution.
3. Cloudflare detection.
4. Public HTTP response.
5. TLS certificate and SNI.
6. Origin TCP reachability.
7. Direct-origin HTTP/HTTPS response when configured.
8. Coolify proxy status and bounded logs.
9. Application container status and health.
10. Docker network connectivity.
11. Host load, memory, and disk.

Each check must return a typed result containing at least:

```python
{
    "name": "...",
    "status": "ok|warning|error|skipped",
    "summary": "...",
    "evidence": {},
    "duration_ms": 0,
    "target": "...",
}
```

The final diagnosis must distinguish evidence from inference. Recommendations
must cite the failed checks that support them.

Do not automatically restart `coolify-proxy`, Coolify, Docker, or the affected
application.

## Error handling

- Use explicit timeouts for network and subprocess operations.
- Bound stdout and stderr retained in memory and reports.
- Preserve partial results when one check fails.
- Convert expected operational failures into typed results.
- Reserve raw exceptions for programming defects or truly unexpected states.
- Provide concise human messages and richer machine-readable details.
- Never claim a check passed if it was skipped.

Recommended statuses:

- `ok`: the check ran and passed.
- `warning`: the check ran and found a nonfatal concern.
- `error`: the check ran and found a failure.
- `skipped`: the check could not run because it was inapplicable or unavailable.

## Python standards

- Support the Python version declared in `pyproject.toml`.
- Use type annotations for public functions and models.
- Prefer Pydantic models for configuration and cross-module result contracts.
- Prefer `pathlib.Path` over string path manipulation.
- Prefer small modules with explicit responsibilities.
- Avoid global mutable state.
- Inject runners and clients so tests can replace them.
- Keep network calls synchronous unless concurrency produces a measured,
  meaningful benefit.
- Use context managers for files and clients.
- Keep comments focused on why, not restating what the code does.

## CLI standards

- Preserve existing command names unless a breaking change is explicitly
  approved.
- Provide `--help` text for commands and non-obvious options.
- Support `--json` for commands used by automation.
- Write result data to stdout.
- Write progress and diagnostics about the CLI itself to stderr.
- Do not emit ANSI styling in JSON mode.
- Keep JSON schemas stable and additive where possible.
- Use consistent exit codes documented in `README.md`.

## Tests

Every behavior change requires tests.

Unit tests must not require:

- Network access.
- Docker.
- SSH.
- A live Coolify instance.
- A live Cloudflare account.
- A connected Tailscale daemon.

Use fakes, dependency injection, mock transports, and sanitized fixtures.

Mark integration tests explicitly. They must be opt-in and must not target
production by default.

For a new provider or diagnostic:

1. Test successful parsing.
2. Test command or request failure.
3. Test timeout behavior.
4. Test malformed output.
5. Test redaction.
6. Test local and SSH command construction where applicable.
7. Test JSON serialization.

For mutation workflows also test:

1. Dry run is the default.
2. Missing `--apply` prevents changes.
3. Configuration can prohibit changes.
4. Exact target confirmation.
5. Verification failure produces a nonzero result.

## Validation

Before handing off a change, run the repository's declared tasks. Typical
commands are:

```bash
uv sync --all-extras
uv run ruff format --check .
uv run ruff check .
uv run pytest
```

If Mise tasks exist, prefer:

```bash
mise run check
```

Also run:

```bash
git diff --check
git status --short
```

Report:

- What changed.
- Which tests ran.
- Whether they passed.
- Any checks not run and why.
- Any new configuration or migration required.

Do not claim validation succeeded if a required tool or service was unavailable.

## Git and file hygiene

- Preserve unrelated user changes.
- Do not reset, clean, or discard work without explicit authorization.
- Do not commit secrets, `.env`, local configuration, reports, or virtual
  environments.
- Keep `.venv/`, caches, generated reports, and private configuration ignored.
- Do not edit `uv.lock` manually.
- Avoid large generated fixtures.
- Make focused commits when the user asks for commits.

## OpenClaw

OpenClaw integration must consume the same public CLI used by humans.

The initial skill should:

- Require the `py-server-manage` executable.
- Use `--json`.
- Prefer public and read-only diagnostic commands.
- Use bounded log tails.
- Never request or display credentials.
- Explain when server-side checks require a configured target.
- Require explicit user approval before any mutation.

Do not rely on prompt instructions as the only mutation control. The CLI itself
must enforce policy.

If an MCP server is added:

- Expose separate read and write tools.
- Keep read tools enabled by default.
- Make write tools independently filterable.
- Validate all arguments with typed schemas.
- Apply the same redaction, timeout, target, dry-run, and audit rules as the CLI.
- Do not expose a generic command-execution tool.

## Implementation sequence

Unless the user requests a different priority, implement in this order:

1. Configuration and typed result models.
2. Secret redaction.
3. Local runner.
4. SSH runner.
5. Console and JSON reporting.
6. Public DNS, HTTP, and TLS probes.
7. Docker and Coolify proxy inspection.
8. `proxy doctor`.
9. Coolify inventory through Coolipy.
10. Tailscale status through the official CLI.
11. Markdown diagnostic reports.
12. Carefully scoped mutation workflows.
13. OpenClaw skill.
14. Optional MCP server.

Complete and test one vertical slice before creating many empty modules.

## Definition of done

A change is complete only when:

- It satisfies the requested behavior.
- Local and SSH execution are considered where relevant.
- Read-only and mutation boundaries remain intact.
- Secret redaction is applied.
- Human and JSON outputs remain coherent.
- Tests cover success and failure paths.
- Documentation and example configuration are updated.
- Formatting, linting, and relevant tests pass.
- No unrelated files or user changes were overwritten.

