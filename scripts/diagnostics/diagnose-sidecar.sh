#!/usr/bin/env bash
# Diagnose Tailscale sidecar + app connectivity (generic).
#
# Usage:
#   diagnose-sidecar.sh --app-container APP --sidecar-container SIDE [options]
#   diagnose-sidecar.sh APP_CONTAINER SIDE_CONTAINER
#
# Options:
#   --app-port PORT          App port to probe (default: 8080)
#   --app-host HOST          Hostname from sidecar to reach app (default: localhost)
#   --tailnet-url URL        HTTPS MagicDNS URL to test from devcontainer
#   --serve-port PORT        Expected tailscale serve HTTPS port (default: 443)
#   --json                   Machine-readable summary line at end
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

APP_CONT=""
SIDE_CONT=""
APP_PORT="${APP_PORT:-8080}"
APP_HOST="${APP_HOST:-localhost}"
TAILNET_URL="${TAILNET_URL:-}"
SERVE_PORT="${SERVE_PORT:-443}"
JSON=false
FAILED=0

usage() {
  sed -n '2,12p' "$0" | sed 's/^# \?//'
  exit 0
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --app-container) APP_CONT="$2"; shift 2 ;;
    --sidecar-container) SIDE_CONT="$2"; shift 2 ;;
    --app-port) APP_PORT="$2"; shift 2 ;;
    --app-host) APP_HOST="$2"; shift 2 ;;
    --tailnet-url) TAILNET_URL="$2"; shift 2 ;;
    --serve-port) SERVE_PORT="$2"; shift 2 ;;
    --json) JSON=true; shift ;;
    -h|--help) usage ;;
    *)
      if [ -z "$APP_CONT" ]; then APP_CONT="$1"
      elif [ -z "$SIDE_CONT" ]; then SIDE_CONT="$1"
      else diag_fail "Unexpected argument: $1"; usage
      fi
      shift
      ;;
  esac
done

if [[ -z "$APP_CONT" || -z "$SIDE_CONT" ]]; then
  usage
fi

ensure_docker_context || exit 1

record_fail() { FAILED=1; }

diag_section "1. Container status"
if container_running "$APP_CONT" && container_running "$SIDE_CONT"; then
  docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' | grep -E "(${APP_CONT}|${SIDE_CONT})" || true
  diag_ok "Both containers running"
else
  record_fail
  docker ps -a --format 'table {{.Names}}\t{{.Status}}' | grep -E "(${APP_CONT}|${SIDE_CONT})" || true
  container_running "$APP_CONT" || diag_fail "App container '$APP_CONT' not running"
  container_running "$SIDE_CONT" || diag_fail "Sidecar container '$SIDE_CONT' not running"
fi

diag_section "2. App port binding (inside app container)"
if container_running "$APP_CONT"; then
  if docker_exec "$APP_CONT" sh -c 'command -v ss >/dev/null && ss -tlnp || netstat -tlnp'; then
    if docker_exec "$APP_CONT" sh -c "ss -tlnp 2>/dev/null || netstat -tlnp" | grep -qE "0\.0\.0\.0:${APP_PORT}|\*:${APP_PORT}|\[::\]:${APP_PORT}"; then
      diag_ok "App listening on 0.0.0.0:${APP_PORT} (or ::)"
    elif docker_exec "$APP_CONT" sh -c "ss -tlnp 2>/dev/null || netstat -tlnp" | grep -q ":${APP_PORT}"; then
      record_fail
      diag_fail "App binds ${APP_PORT} but possibly only on 127.0.0.1 — sidecar may not reach it"
      diag_info "Fix: bind app to 0.0.0.0:${APP_PORT} or set --app-host to the compose service name"
    else
      record_fail
      diag_fail "Nothing listening on port ${APP_PORT} inside app container"
    fi
  else
    record_fail
    diag_fail "Could not inspect listeners in app container"
  fi
else
  record_fail
  diag_fail "Skipped — app container not running"
fi

diag_section "3. Sidecar Tailscale status"
if container_running "$SIDE_CONT"; then
  if docker_exec "$SIDE_CONT" tailscale status; then
    if docker_exec "$SIDE_CONT" tailscale status 2>&1 | grep -qiE 'logged out|needs login|Stopped'; then
      record_fail
      diag_fail "Tailscale not authenticated in sidecar — check TS_AUTHKEY / state volume"
    else
      diag_ok "Tailscale reports online"
    fi
  else
    record_fail
    diag_fail "tailscale status failed inside sidecar"
  fi
else
  record_fail
  diag_fail "Skipped — sidecar not running"
fi

diag_section "4. Sidecar tailscale serve"
if container_running "$SIDE_CONT"; then
  if docker_exec "$SIDE_CONT" tailscale serve status; then
    if docker_exec "$SIDE_CONT" tailscale serve status 2>&1 | grep -qi 'No serve config'; then
      record_fail
      diag_fail "No tailscale serve config — HTTPS tailnet URL will not work"
      diag_info "Fix: tailscale serve --bg --https=${SERVE_PORT} http://${APP_HOST}:${APP_PORT}"
    else
      diag_ok "tailscale serve configured"
    fi
  else
    record_fail
    diag_warn "Could not read tailscale serve status"
  fi
fi

diag_section "5. Internal connectivity (sidecar → app)"
if container_running "$SIDE_CONT"; then
  local_url="http://${APP_HOST}:${APP_PORT}/"
  diag_info "Probing ${local_url} from sidecar..."
  if docker_http_head "$SIDE_CONT" "$local_url"; then
    diag_ok "Sidecar reaches app at ${APP_HOST}:${APP_PORT}"
  else
    record_fail
    diag_fail "Sidecar cannot reach app at ${APP_HOST}:${APP_PORT}"
    diag_info "Try --app-host <compose_service_name> if not sharing network namespace"
    diag_info "Common fix: app binds 127.0.0.1 only — change to 0.0.0.0"
  fi
else
  record_fail
  diag_fail "Skipped — sidecar not running"
fi

diag_section "6. Sidecar MagicDNS / tailnet IP"
if container_running "$SIDE_CONT"; then
  sidecar_ip="$(docker_exec "$SIDE_CONT" tailscale ip -4 || true)"
  sidecar_dns="$(docker_exec "$SIDE_CONT" tailscale status --json 2>/dev/null | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print(d.get('Self',{}).get('DNSName','').rstrip('.'))
except Exception:
  pass
" 2>/dev/null || true)"
  if [ -n "$sidecar_ip" ]; then
    diag_ok "Sidecar tailnet IPv4: ${sidecar_ip}"
  else
    record_fail
    diag_fail "No tailnet IPv4 on sidecar"
  fi
  if [ -n "$sidecar_dns" ]; then
    diag_ok "Sidecar MagicDNS: ${sidecar_dns}"
  else
    diag_warn "Could not read MagicDNS name from sidecar"
  fi
fi

diag_section "7. TSMP ping (sidecar → self tailnet IP)"
if container_running "$SIDE_CONT" && [ -n "${sidecar_ip:-}" ]; then
  if docker_exec "$SIDE_CONT" tailscale ping "$sidecar_ip" --tsmp --c 3; then
    diag_ok "TSMP ping to own tailnet IP succeeded"
  else
    record_fail
    diag_fail "TSMP ping failed — tailnet dataplane issue inside sidecar"
  fi
fi

diag_section "8. Reachability from devcontainer (tailnet URL)"
if [ -n "$TAILNET_URL" ]; then
  diag_info "curl -kI ${TAILNET_URL}"
  if curl -kfsSI --connect-timeout 10 "$TAILNET_URL" 2>&1; then
    diag_ok "Tailnet URL reachable from devcontainer"
  else
    record_fail
    diag_fail "Tailnet URL not reachable from devcontainer"
    diag_info "Check: tailscale serve, ACLs, devcontainer tailscale up, correct hostname"
  fi
elif [ -n "${sidecar_dns:-}" ]; then
  guessed_url="https://${sidecar_dns}:${SERVE_PORT}/"
  diag_info "No --tailnet-url; trying ${guessed_url}"
  if curl -kfsSI --connect-timeout 10 "$guessed_url" 2>&1; then
    diag_ok "Guessed tailnet URL reachable"
  else
    record_fail
    diag_fail "Guessed tailnet URL failed — pass --tailnet-url explicitly"
  fi
else
  diag_warn "Skipped — set --tailnet-url or ensure sidecar has MagicDNS"
fi

diag_section "Diagnosis summary"
if [ "$FAILED" -eq 0 ]; then
  diag_ok "All checks passed"
else
  diag_fail "One or more checks failed — see sections above"
  diag_info "Binding 127.0.0.1 → use 0.0.0.0"
  diag_info "No tailscale serve → run serve after every sidecar deploy"
  diag_info "Wrong app-host → use compose service name on shared docker network"
  diag_info "Tailscale logged out → TS_AUTHKEY, TS_STATE_DIR volume, NET_ADMIN + /dev/net/tun"
fi

if [ "$JSON" = true ]; then
  printf '{"app":"%s","sidecar":"%s","failed":%s}\n' "$APP_CONT" "$SIDE_CONT" "$FAILED"
fi

exit "$FAILED"
