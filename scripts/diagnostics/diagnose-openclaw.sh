#!/usr/bin/env bash
# Diagnose OpenClaw tailnet IP / URL not working.
#
# Discovers OpenClaw app + Tailscale sidecar containers (or uses env overrides),
# then runs sidecar + tailnet URL diagnostics.
#
# Usage:
#   diagnose-openclaw.sh [options]
#
# Environment overrides:
#   OPENCLAW_APP_CONTAINER      App container name
#   OPENCLAW_SIDECAR_CONTAINER  Sidecar container name
#   OPENCLAW_APP_PORT           App port (default 8080)
#   OPENCLAW_APP_HOST           Host sidecar uses to reach app (default: localhost)
#   OPENCLAW_TAILNET_URL        Full HTTPS URL to test (e.g. https://openclaw.tailnet.ts.net)
#
# Options: same as diagnose-sidecar.sh (--app-port, --tailnet-url, etc.)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

APP_CONT="${OPENCLAW_APP_CONTAINER:-}"
SIDE_CONT="${OPENCLAW_SIDECAR_CONTAINER:-}"
APP_PORT="${OPENCLAW_APP_PORT:-8080}"
APP_HOST="${OPENCLAW_APP_HOST:-localhost}"
TAILNET_URL="${OPENCLAW_TAILNET_URL:-}"
EXTRA_ARGS=()

usage() {
  sed -n '2,16p' "$0" | sed 's/^# \?//'
  exit 0
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-container) APP_CONT="$2"; shift 2 ;;
    --sidecar-container) SIDE_CONT="$2"; shift 2 ;;
    --app-port) APP_PORT="$2"; shift 2 ;;
    --app-host) APP_HOST="$2"; shift 2 ;;
    --tailnet-url) TAILNET_URL="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) EXTRA_ARGS+=("$1"); shift ;;
  esac
done

ensure_docker_context || exit 1

discover_containers() {
  diag_section "0. Discover OpenClaw containers"

  if [ -z "$APP_CONT" ]; then
    APP_CONT="$(find_container 'openclaw' | grep -viE 'tailscale|ts-|sidecar' | head -1 || true)"
    [ -z "$APP_CONT" ] && APP_CONT="$(find_container 'openclaw' || true)"
  fi

  if [ -n "$APP_CONT" ]; then
    diag_ok "App container: ${APP_CONT}"
  else
    diag_fail "Could not find OpenClaw app container"
    diag_info "Set OPENCLAW_APP_CONTAINER or pass --app-container"
    docker ps --format '{{.Names}}' | grep -i openclaw || docker ps --format '{{.Names}}' | head -20
    exit 1
  fi

  if resolve_sidecar_from_app "$APP_CONT"; then
    diag_ok "Coolify sidecar pattern: ${SIDECAR_NAME} (shared network namespace)"
    USE_COOLIFY_PATTERN=true
    SIDE_CONT="$SIDECAR_NAME"
    return 0
  fi

  USE_COOLIFY_PATTERN=false
  if [ -z "$SIDE_CONT" ]; then
    SIDE_CONT="$(find_container 'openclaw.*(tailscale|ts-|sidecar)|tailscale.*openclaw' || true)"
    [ -z "$SIDE_CONT" ] && SIDE_CONT="$(find_container 'tailscale' | grep -i openclaw | head -1 || true)"
  fi

  if [ -n "$SIDE_CONT" ]; then
    diag_ok "Sidecar container (separate): ${SIDE_CONT}"
  else
    diag_fail "Could not find OpenClaw Tailscale sidecar"
    diag_info "Set OPENCLAW_SIDECAR_CONTAINER or pass --sidecar-container"
    docker ps -a --format '{{.Names}}' | grep -iE 'openclaw|tailscale' || true
    exit 1
  fi
}

USE_COOLIFY_PATTERN=false
discover_containers

diag_section "OpenClaw logs (last 30 lines)"
docker logs "$APP_CONT" --tail 30 2>&1 | tail -30 || true
if [ -n "${SIDE_CONT:-}" ]; then
  diag_info "--- sidecar ---"
  docker logs "$SIDE_CONT" --tail 30 2>&1 | tail -30 || true
fi

if [ "$USE_COOLIFY_PATTERN" = true ]; then
  diag_section "Coolify sidecar survey (network_mode: service:sidecar)"
  bash "${SCRIPT_DIR}/diagnose-coolify-sidecar.sh" "$APP_CONT"
  sidecar_rc=$?
else
  SIDECAR_ARGS=(
    --app-container "$APP_CONT"
    --sidecar-container "$SIDE_CONT"
    --app-port "$APP_PORT"
    --app-host "$APP_HOST"
  )
  [ -n "$TAILNET_URL" ] && SIDECAR_ARGS+=(--tailnet-url "$TAILNET_URL")
  SIDECAR_ARGS+=("${EXTRA_ARGS[@]}")
  bash "${SCRIPT_DIR}/diagnose-sidecar.sh" "${SIDECAR_ARGS[@]}"
  sidecar_rc=$?
fi

if [ -n "$TAILNET_URL" ]; then
  bash "${SCRIPT_DIR}/diagnose-tailnet-url.sh" --url "$TAILNET_URL"
  url_rc=$?
else
  url_rc=0
  diag_warn "Set OPENCLAW_TAILNET_URL for full URL diagnostics from devcontainer"
fi

diag_section "OpenClaw remediation checklist"
if [ "$USE_COOLIFY_PATTERN" = true ]; then
  diag_info "1. tailscale serve configured: fix-tailscale-https.sh ${APP_CONT} ${APP_PORT}"
  diag_info "2. TS_SERVE_CONFIG is a file not directory: fix-ts-serve-config-mount.sh ${APP_CONT}"
  diag_info "3. HTTPS Certificates enabled in tailnet admin console"
  diag_info "4. App listens on localhost:${APP_PORT} inside shared netns"
else
  diag_info "1. App listens 0.0.0.0:${APP_PORT} (not 127.0.0.1 only)"
  diag_info "2. Sidecar tailscale up + persistent TS_STATE_DIR"
  diag_info "3. tailscale serve --bg --https=443 http://${APP_HOST}:${APP_PORT}"
fi
diag_info "4. ACL allows devcontainer → openclaw sidecar"
diag_info "5. Redeploy wiped serve? Fix Storages + entrypoint"
diag_info "Doc: docs/workflows/openclaw-tailnet-down.md"

exit $(( sidecar_rc || url_rc ))
