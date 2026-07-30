#!/usr/bin/env bash
# Repair Coolify bug: TS_SERVE_CONFIG bind-mounted as directory instead of file.
#
# Usage:
#   fix-ts-serve-config-mount.sh [--yes] [--force] <app-container-name>
#
# Host filesystem changes run on the Docker host (SSH when COOLIFY_DOCKER_HOST set).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

ASSUME_YES=false
FORCE=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=true; shift ;;
    -f|--force) FORCE=true; shift ;;
    -h|--help)
      sed -n '2,7p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) break ;;
  esac
done

APP="${1:?Usage: $0 [--yes] [--force] <app-container-name>}"

ensure_docker_context || exit 1

if ! resolve_sidecar_from_app "$APP"; then
  diag_fail "App '$APP' is not using network_mode: service:<sidecar>"
  exit 1
fi

diag_info "Sidecar: ${SIDECAR_NAME} (${SIDECAR_ID})"

TS_SERVE_CONFIG_IN_CONTAINER="$(docker exec "$SIDECAR_ID" printenv TS_SERVE_CONFIG 2>/dev/null || true)"
if [[ -z "$TS_SERVE_CONFIG_IN_CONTAINER" ]]; then
  diag_fail "TS_SERVE_CONFIG not set in sidecar"
  exit 1
fi

HOST_SRC="$(docker inspect "$SIDECAR_ID" --format '{{range .Mounts}}{{if eq .Destination "'"$TS_SERVE_CONFIG_IN_CONTAINER"'"}}{{.Source}}{{end}}{{end}}')"
if [[ -z "$HOST_SRC" ]]; then
  diag_fail "No mount found for destination ${TS_SERVE_CONFIG_IN_CONTAINER}"
  exit 1
fi

diag_info "Host mount source: ${HOST_SRC}"

if run_on_docker_host "[ -f '${HOST_SRC}' ]"; then
  diag_ok "Host source is already a file — nothing to fix"
  exit 0
fi

if run_on_docker_host "[ -d '${HOST_SRC}' ]"; then
  diag_warn "Host source is a DIRECTORY (the bug)"
else
  diag_info "Host source missing — will create file"
fi

confirm_or_abort "Stop sidecar '${SIDECAR_NAME}', repair mount, and restart? [y/N] " "$ASSUME_YES" || {
  diag_info "Aborted"
  exit 0
}

docker stop "$SIDECAR_ID" >/dev/null

if run_on_docker_host "[ -d '${HOST_SRC}' ]"; then
  if [ "$FORCE" = true ]; then
    run_on_docker_host "rm -rf '${HOST_SRC}'"
  else
    if ! run_on_docker_host "rmdir '${HOST_SRC}' 2>/dev/null"; then
      diag_fail "Directory not empty: ${HOST_SRC}"
      diag_info "Re-run with --force to remove, or fix manually"
      docker start "$SIDECAR_ID" >/dev/null
      exit 1
    fi
  fi
fi

run_on_docker_host "touch '${HOST_SRC}' && chown 1000:1000 '${HOST_SRC}' 2>/dev/null || true"

docker start "$SIDECAR_ID" >/dev/null
sleep 2

if docker exec "$SIDECAR_ID" bash -c "[ -f '${TS_SERVE_CONFIG_IN_CONTAINER}' ]"; then
  diag_ok "TS_SERVE_CONFIG is now a file"
else
  diag_fail "Mount still broken after fix"
  exit 1
fi

cat <<'NOTE'

NOTE: Fix the Coolify service Storages tab so TS_SERVE_CONFIG is a file mount,
not a directory — otherwise the bug returns on next redeploy.
See docs/workflows/tailscale-serve-https.md
NOTE
