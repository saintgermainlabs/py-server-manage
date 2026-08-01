#!/usr/bin/env bash
# Read-only dry-run: list probable database containers and proposed dump methods.
# Does not dump databases or mutate system state.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

UV_BIN="${UV_BIN:-}"
if [[ -z "$UV_BIN" ]]; then
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  elif [[ -x "$HOME/.local/bin/uv" ]]; then
    UV_BIN="$HOME/.local/bin/uv"
  else
    echo "uv not found; set UV_BIN or install uv" >&2
    exit 1
  fi
fi

CONFIG_ARGS=()
if [[ -f /etc/server-backup/backup.yaml ]]; then
  CONFIG_ARGS=(--config /etc/server-backup/backup.yaml)
fi

exec "$UV_BIN" run serverops backup discover-databases "${CONFIG_ARGS[@]}" "$@"
