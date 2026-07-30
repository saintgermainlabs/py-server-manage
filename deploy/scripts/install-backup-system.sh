#!/usr/bin/env bash
# Install or preview ServerOps backup scaffolding on the Hetzner host.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

MODE="dry-run"
FORCE=0
CONFIG_ARG=()

usage() {
  cat <<'EOF'
Usage: install-backup-system.sh [--dry-run|--apply] [--force] [--config PATH]

Defaults to --dry-run. Requires uv and this repository checked out
(e.g. /opt/py-server-manage). Run on the backup host as root.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --config)
      CONFIG_ARG=(--config "$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ ! -x "$ROOT/.venv/bin/serverops" ]]; then
  echo "Missing $ROOT/.venv/bin/serverops — run: uv sync --all-extras" >&2
  exit 1
fi

ARGS=(backup install)
if [[ "$MODE" == "apply" ]]; then
  ARGS+=(--apply)
else
  ARGS+=(--dry-run)
fi
if [[ "$FORCE" -eq 1 ]]; then
  ARGS+=(--force)
fi
if [[ ${#CONFIG_ARG[@]} -gt 0 ]]; then
  ARGS+=("${CONFIG_ARG[@]}")
fi

exec "$ROOT/.venv/bin/serverops" "${ARGS[@]}"
