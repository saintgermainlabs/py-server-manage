"""Native database dump helpers (Phase 4+).

Allowlist contract: `serverops.backup.databases_config` and
`config/databases.example.yaml`, rendered on the host via Vault Agent
(`deploy/vault-agent/templates/databases.yaml.ctmpl`).
"""

from __future__ import annotations


def dump_databases() -> None:
    raise NotImplementedError(
        "database dump pipeline is not implemented yet; "
        "define allowlist in /etc/server-backup/databases.yaml "
        "(Vault Agent template under deploy/vault-agent/)"
    )
