#!/usr/bin/env bash
# Configure tailscale serve for HTTPS on a Coolify app's sidecar (shared netns).
#
# Usage:
#   fix-tailscale-https.sh <app-container-name> [internal-port]
#   fix-tailscale-https.sh --yes openclaw 8080
#
# internal-port defaults to 80. With network_mode: service:<sidecar>, the app
# listens on localhost inside the sidecar namespace.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

ASSUME_YES=false
while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) ASSUME_YES=true; shift ;;
    -h|--help)
      sed -n '2,10p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *) break ;;
  esac
done

APP="${1:?Usage: $0 [--yes] <app-container-name> [internal-port]}"
PORT="${2:-80}"

ensure_docker_context || exit 1

if ! resolve_sidecar_from_app "$APP"; then
  netmode="$(docker inspect "$APP" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true)"
  diag_fail "App '$APP' is not using network_mode: service:<sidecar> (got '$netmode')"
  exit 1
fi

diag_info "Sidecar: ${SIDECAR_NAME} (${SIDECAR_ID})"

docker exec "$SIDECAR_ID" tailscale status || true

FQDN="$(docker exec "$SIDECAR_ID" tailscale status --json 2>/dev/null | python3 -c "
import json,sys
try:
  print(json.load(sys.stdin).get('Self',{}).get('DNSName','').rstrip('.'))
except Exception:
  pass
" 2>/dev/null || true)"

if [[ -n "$FQDN" ]]; then
  diag_info "Tailnet DNS name: ${FQDN}"
else
  diag_warn "Could not determine tailnet DNSName — is sidecar logged in?"
fi

diag_section "TLS cert (requires HTTPS Certificates in tailnet admin)"
if [[ -n "$FQDN" ]]; then
  cert_out="$(mktemp)"
  if docker exec "$SIDECAR_ID" tailscale cert "${FQDN}" >"$cert_out" 2>&1; then
    diag_ok "Cert OK for ${FQDN}"
  else
    if grep -qi "HTTPS is not enabled" "$cert_out"; then
      diag_fail "HTTPS Certificates disabled for this tailnet"
      diag_info "Enable: https://login.tailscale.com/admin/settings/general"
      rm -f "$cert_out"
      exit 2
    fi
    diag_warn "Cert step failed (may still proceed):"
    cat "$cert_out" >&2
  fi
  rm -f "$cert_out"
fi

diag_section "Configure tailscale serve"
diag_info "https:443 -> http://localhost:${PORT}"
docker exec "$SIDECAR_ID" tailscale serve --bg --https=443 "http://localhost:${PORT}"

docker exec "$SIDECAR_ID" tailscale serve status

diag_info "If serve resets on redeploy, run: fix-ts-serve-config-mount.sh ${APP}"
diag_info "Doc: docs/workflows/tailscale-serve-https.md"
