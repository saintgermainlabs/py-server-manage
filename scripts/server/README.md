# Server scripts

Place scripts copied from your live Coolify host here.

## Expected layout

```
scripts/server/
├── README.md           # this file
├── <service-name>/     # grouped by service or purpose
│   └── *.sh
└── common/             # shared helpers
```

## Conventions

- Use `set -euo pipefail`
- Support `--dry-run` where destructive
- Document required env vars at top of each script
- Link each script from the relevant doc in `docs/`

## Integration

When adding scripts from previous projects or the live server:

1. Copy into the appropriate subdirectory
2. `chmod +x` executable scripts
3. Add a row to the index below
4. Reference from `docs/coolify/debug.md` or `docs/workflows/` if operational

## Index

| Script | Purpose | Source |
|--------|---------|--------|
| _(pending)_ | User-provided assets | — |
| `diagnose-openclaw.sh` | OpenClaw tailnet URL diagnostics | [scripts/diagnostics/](../diagnostics/diagnose-openclaw.sh) |

Drop your files here and update this index.
