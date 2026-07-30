#!/usr/bin/env bash
# Run layered diagnostics for the devops stack.
#
# Usage:
#   diagnose-stack.sh [--quick|--full] [--openclaw]
#
# --quick   devcontainer health only
# --full    health + docker inventory + optional openclaw
# --openclaw  include OpenClaw sidecar diagnostics
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIAG_DIR="${REPO_ROOT}/scripts/diagnostics"
MODE="full"
OPENCLAW=false
FAILED=0

while [ "$#" -gt 0 ]; do
  case "$1" in
    --quick) MODE="quick"; shift ;;
    --full) MODE="full"; shift ;;
    --openclaw) OPENCLAW=true; shift ;;
    -h|--help)
      sed -n '2,8p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done

run_check() {
  local label="$1"
  shift
  printf '\n========== %s ==========\n' "$label"
  if "$@"; then
    printf 'OK: %s\n' "$label"
  else
    printf 'FAIL: %s\n' "$label" >&2
    FAILED=1
  fi
}

export PATH="${HOME}/.local/bin:${PATH}"

run_check "Devcontainer health" bash "${REPO_ROOT}/.devcontainer/scripts/check_health.sh"

if [ "$MODE" = "quick" ]; then
  exit "$FAILED"
fi

if command -v coolify_diag >/dev/null 2>&1; then
  run_check "Coolify + Tailscale diag" bash -c 'coolify_diag' || true
fi

if command -v cdiag >/dev/null 2>&1; then
  run_check "Docker inventory" bash -c 'cdiag' || true
else
  run_check "Docker ps" docker ps
fi

if [ "$OPENCLAW" = true ] || [ -n "${OPENCLAW_TAILNET_URL:-}" ]; then
  run_check "OpenClaw tailnet" bash "${DIAG_DIR}/diagnose-openclaw.sh" || true
fi

exit "$FAILED"
