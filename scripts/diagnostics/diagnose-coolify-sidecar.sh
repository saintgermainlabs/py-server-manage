#!/usr/bin/env bash
# Survey Coolify-managed containers using network_mode: service:<sidecar>.
#
# Checks TS_SERVE_CONFIG mount type (file vs directory bug), tailscale serve,
# and HTTPS on localhost:443 inside the shared network namespace.
#
# Usage:
#   diagnose-coolify-sidecar.sh [container-name-filter]
#
# Run from devcontainer (local profile uses remote Docker via COOLIFY_DOCKER_HOST).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

TARGET="${1:-}"
FAILED=0

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \?//'
  exit 0
}

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && usage

ensure_docker_context || exit 1

if [[ -n "$TARGET" ]]; then
  CONTAINERS="$(docker ps --format '{{.Names}}' | grep -F "$TARGET" || true)"
else
  CONTAINERS="$(docker ps --format '{{.Names}}')"
fi

if [[ -z "$CONTAINERS" ]]; then
  diag_fail "No matching running containers found"
  exit 1
fi

for c in $CONTAINERS; do
  if [[ -z "$TARGET" ]] && [[ "$c" == *tailscale* || "$c" == ts-* ]]; then
    continue
  fi

  diag_section_b "$c"

  if resolve_sidecar_from_app "$c"; then
    diag_ok_b "App uses sidecar network: ${SIDECAR_NAME}"
  elif resolve_sidecar_for_stack "$c"; then
    sm="$(docker inspect "$SIDECAR_NAME" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true)"
    diag_ok_b "Paired sidecar: ${SIDECAR_NAME} (sidecar NetworkMode=${sm})"
  else
    netmode="$(docker inspect "$c" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true)"
    diag_warn_b "No sidecar found for '$c' (NetworkMode=${netmode}). Skipping."
    continue
  fi

  sidecar_state="$(docker inspect "$SIDECAR_NAME" --format '{{.State.Status}}' 2>/dev/null || true)"
  if [[ "$sidecar_state" == "running" ]]; then
    diag_ok_b "Sidecar '${SIDECAR_NAME}' is running"
  else
    diag_fail_b "Sidecar '${SIDECAR_NAME}' is '${sidecar_state}'"
    FAILED=1
    continue
  fi

  ts_status="$(docker exec "$SIDECAR_NAME" tailscale status --json 2>/dev/null || true)"
  if [[ -z "$ts_status" ]]; then
    diag_fail_b "Could not run tailscale status inside sidecar"
    FAILED=1
  else
    backend_state="$(echo "$ts_status" | python3 -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print(d.get('BackendState',''))
except Exception:
  pass
" 2>/dev/null || true)"
    ts_online="$(echo "$ts_status" | python3 -c "
import json,sys
try:
  print(json.load(sys.stdin).get('Self',{}).get('Online', False))
except Exception:
  pass
" 2>/dev/null || true)"
    ts_dns="$(echo "$ts_status" | python3 -c "
import json,sys
try:
  print(json.load(sys.stdin).get('Self',{}).get('DNSName','').rstrip('.'))
except Exception:
  pass
" 2>/dev/null || true)"
    if [[ "$backend_state" == "Running" ]]; then
      diag_ok_b "tailscale backend state: Running"
    else
      diag_fail_b "tailscale backend state: ${backend_state:-unknown}"
      FAILED=1
    fi
    if [[ "$ts_online" == "True" ]]; then
      diag_ok_b "tailnet Online: true (${ts_dns})"
    else
      diag_fail_b "tailnet Online: false (${ts_dns}) — peers cannot reach this node"
      FAILED=1
    fi
    if [[ "$ts_dns" =~ ^[0-9a-f]{12}\. ]]; then
      diag_warn_b "MagicDNS uses container ID ($ts_dns) — set TS_HOSTNAME=openclaw in sidecar env"
    fi
  fi

  if sidecar_netns_split "$SIDECAR_NAME"; then
    diag_fail_b "Split network namespace: sidecar has tailscale0 but no eth0/default route"
    diag_info "serve localhost:8080 cannot reach app — fix compose: openclaw network_mode: service:tailscale"
    diag_info "See docs/coolify/openclaw-incident-2026-07-20.md"
    FAILED=1
  fi

  ts_serve_config_path="$(docker exec "$SIDECAR_NAME" printenv TS_SERVE_CONFIG 2>/dev/null || true)"
  if [[ -n "$ts_serve_config_path" ]]; then
    mount_type="$(docker exec "$SIDECAR_NAME" sh -c "[ -d '$ts_serve_config_path' ] && echo dir || ([ -f '$ts_serve_config_path' ] && echo file || echo missing)" 2>/dev/null || true)"
    case "$mount_type" in
      file)    diag_ok_b "TS_SERVE_CONFIG ($ts_serve_config_path) is a file" ;;
      dir)
        diag_fail_b "TS_SERVE_CONFIG ($ts_serve_config_path) is a DIRECTORY — Coolify bug"
        diag_info "Fix: bash scripts/diagnostics/fix-ts-serve-config-mount.sh $c"
        FAILED=1
        ;;
      missing) diag_warn_b "TS_SERVE_CONFIG ($ts_serve_config_path) missing (ok if serve not configured yet)" ;;
    esac
  else
    diag_warn_b "TS_SERVE_CONFIG not set in sidecar"
  fi

  serve_status="$(docker exec "$SIDECAR_NAME" tailscale serve status 2>&1 || true)"
  if echo "$serve_status" | grep -qi "no serve config"; then
    diag_fail_b "No tailscale serve config — HTTPS tailnet URL will fail"
    diag_info "Fix: bash scripts/diagnostics/fix-tailscale-https.sh $c [port]"
    FAILED=1
  else
    diag_ok_b "tailscale serve config present:"
    echo "$serve_status" | sed 's/^/         /'
  fi

  https_check="$(docker exec "$SIDECAR_NAME" sh -c "wget -qSO- --timeout=3 https://127.0.0.1:443/ 2>&1 | head -1 || curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1:443 --max-time 3" 2>/dev/null || true)"
  if [[ "$https_check" =~ ^[23] ]]; then
    diag_ok_b "https://localhost:443 responds inside sidecar (HTTP $https_check)"
  else
    diag_fail_b "https://localhost:443 not responding inside sidecar (got '$https_check')"
    FAILED=1
  fi
done

printf '\n'
if [ "$FAILED" -eq 0 ]; then
  diag_ok "Coolify sidecar survey complete — no failures"
else
  diag_fail "Failures detected — see fix commands above"
fi

exit "$FAILED"
