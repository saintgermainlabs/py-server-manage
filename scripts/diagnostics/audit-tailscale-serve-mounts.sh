#!/usr/bin/env bash
# Audit Tailscale sidecars for shared serve.json mounts from /opt/tailscale/serve.
#
# Usage:
#   audit-tailscale-serve-mounts.sh
#   audit-tailscale-serve-mounts.sh openclaw
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

TARGET="${1:-}"
HOST_ROOT="${TAILSCALE_SERVE_HOST_ROOT:-/opt/tailscale/serve}"
FAILED=0

ensure_docker_context || exit 1

record_fail() { FAILED=1; }

audit_container() {
  local sidecar="$1"
  local app_guess=""
  app_guess="$(echo "$sidecar" | sed -E 's/^tailscale-//; s/-[a-z0-9]{20,}$//; s/^tailscale-//')"

  diag_section_b "$sidecar"

  ts_cfg="$(docker_exec "$sidecar" printenv TS_SERVE_CONFIG 2>/dev/null || true)"
  if [ -z "$ts_cfg" ]; then
    record_fail
    diag_fail_b "TS_SERVE_CONFIG not set"
    diag_info "Set TS_SERVE_CONFIG=/config/serve/serve.json on sidecar"
    return
  fi
  diag_ok_b "TS_SERVE_CONFIG=${ts_cfg}"

  mount_src="$(docker inspect "$sidecar" --format '{{range .Mounts}}{{if eq .Destination "/config/serve"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"
  if [ -z "$mount_src" ]; then
    mount_src="$(docker inspect "$sidecar" --format '{{range .Mounts}}{{if eq .Destination "/config/serve/serve.json"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"
  fi

  if [[ "$mount_src" == "${HOST_ROOT}/"* ]]; then
    diag_ok_b "Mount from shared host root: ${mount_src}"
  elif [ -n "$mount_src" ]; then
    diag_warn_b "Mount not under ${HOST_ROOT}: ${mount_src}"
    diag_info "Prefer: ${HOST_ROOT}/<app>:/config/serve:ro"
  else
    record_fail
    diag_fail_b "No /config/serve directory mount found"
    diag_info "Coolify Storages: Host ${HOST_ROOT}/<app> → Container /config/serve"
  fi

  if docker_exec "$sidecar" sh -c "[ -f '${ts_cfg}' ]"; then
    diag_ok_b "serve.json is a file"
    proxy="$(docker_exec "$sidecar" sh -c "grep -o 'http://[^\"]*' '${ts_cfg}' 2>/dev/null | head -1" || true)"
    [ -n "$proxy" ] && diag_info "Backend: ${proxy}"
  elif docker_exec "$sidecar" sh -c "[ -d '${ts_cfg}' ]"; then
    record_fail
    diag_fail_b "TS_SERVE_CONFIG path is a DIRECTORY (Coolify bug)"
    diag_info "Fix: bash scripts/diagnostics/fix-ts-serve-config-mount.sh <app-container>"
  else
    record_fail
    diag_fail_b "serve.json missing at ${ts_cfg}"
  fi

  if container_running "$sidecar"; then
    serve_out="$(docker_exec "$sidecar" tailscale serve status 2>&1 || true)"
    if echo "$serve_out" | grep -qi 'no serve config'; then
      record_fail
      diag_fail_b "No active tailscale serve config"
    else
      diag_ok_b "tailscale serve active"
    fi
  fi
}

if [ -n "$TARGET" ]; then
  sidecars="$(docker ps --format '{{.Names}}' | grep -iE 'tailscale' | grep -F "$TARGET" || true)"
else
  sidecars="$(docker ps --format '{{.Names}}' | grep -iE '^tailscale-|tailscale-' || true)"
fi

if [ -z "$sidecars" ]; then
  diag_fail "No tailscale sidecar containers found"
  exit 1
fi

diag_section "Tailscale serve mount audit (host root: ${HOST_ROOT})"
for c in $sidecars; do
  audit_container "$c"
done

printf '\n'
[ "$FAILED" -eq 0 ] && diag_ok "All sidecars use shared serve layout" || diag_fail "Issues found — see above"
exit "$FAILED"
