---
name: serverops
description: Safely inspect, diagnose, and manage Coolify and standalone server deployments with the serverops CLI.
metadata:
  openclaw:
    requires:
      bins: ["serverops"]
---

# ServerOps

Use `serverops` for infrastructure diagnostics and Coolify API operations.

The CLI is modular:

- `serverops debug ...` — host/Docker diagnostics
- `serverops coolify ...` — Coolify API and inventory
- `serverops tailscale ...` — Tailscale inventories
- `serverops inventory ...` — dashboard/template transforms
- `serverops openclaw ...` — OpenClaw skill helpers

## Safety contract

- Begin with read-only commands.
- Use `--json` whenever you need to reason about the result.
- Never enable `allow_mutations` or pass `--apply` without explicit user approval.
- Never print, read, or request Coolify or Tailscale API tokens.
- Before a mutation, show the user the dry-run result and state the exact target.
- Do not run arbitrary shell commands through this skill.

## Common commands

```bash
serverops --json doctor
serverops --json debug doctor
serverops --json docker ps --all
serverops --json docker logs CONTAINER --tail 200
serverops --json coolify health
serverops --json coolify get /servers
serverops --json coolify get /applications
serverops --json openclaw skill
```

For a named SSH target:

```bash
serverops --target production --json doctor
```

Preview a mutating Coolify call:

```bash
serverops --json coolify request POST /deployments --data '{"uuid":"..."}'
```

Only after explicit approval and only when the local config allows mutations:

```bash
serverops --json coolify request POST /deployments --data '{"uuid":"..."}' --apply
```
