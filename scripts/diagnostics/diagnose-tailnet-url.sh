#!/usr/bin/env bash
# Test tailnet hostname / IP / URL reachability from the devcontainer.
#
# Usage:
#   diagnose-tailnet-url.sh --url https://openclaw.example.ts.net
#   diagnose-tailnet-url.sh --host openclaw.example.ts.net [--port 443]
#   diagnose-tailnet-url.sh --ip 100.x.x.x [--port 443]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

URL=""
HOST=""
IP=""
PORT="443"
SCHEME="https"
FAILED=0

usage() {
  sed -n '2,7p' "$0" | sed 's/^# \?//'
  exit 0
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --url) URL="$2"; shift 2 ;;
    --host) HOST="$2"; shift 2 ;;
    --ip) IP="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --http) SCHEME="http"; shift ;;
    -h|--help) usage ;;
    *) diag_fail "Unknown option: $1"; usage ;;
  esac
done

record_fail() { FAILED=1; }

if [ -z "$URL" ]; then
  if [ -n "$HOST" ]; then
    URL="${SCHEME}://${HOST}:${PORT}/"
  elif [ -n "$IP" ]; then
    URL="${SCHEME}://${IP}:${PORT}/"
  else
    usage
  fi
fi

diag_section "1. Devcontainer Tailscale"
if command -v tailscale >/dev/null 2>&1; then
  if tailscale status >/dev/null 2>&1; then
    diag_ok "Devcontainer on tailnet"
    tailscale status 2>/dev/null | head -8
  else
    record_fail
    diag_fail "Devcontainer tailscale not connected — run post-start or tailscale up"
  fi
else
  record_fail
  diag_fail "tailscale CLI not installed"
fi

diag_section "2. DNS resolution"
host_part="$(echo "$URL" | sed -E 's|https?://([^/:]+).*|\1|')"
if [[ "$host_part" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  diag_info "Target is IP: ${host_part}"
else
  if getent hosts "$host_part" >/dev/null 2>&1 || host "$host_part" >/dev/null 2>&1; then
    diag_ok "DNS resolves: ${host_part}"
    getent hosts "$host_part" 2>/dev/null || host "$host_part" 2>/dev/null || true
  else
    record_fail
    diag_fail "DNS does not resolve: ${host_part}"
    diag_info "Check MagicDNS, tailnet membership, hostname spelling"
  fi
fi

diag_section "3. Tailscale ping (devcontainer → target)"
if command -v tailscale >/dev/null 2>&1 && tailscale status >/dev/null 2>&1; then
  ping_target="$host_part"
  if tailscale ping "$ping_target" --c 3 2>&1; then
    diag_ok "tailscale ping succeeded"
  else
    record_fail
    diag_fail "tailscale ping failed — ACL, offline peer, or wrong hostname"
  fi
else
  diag_warn "Skipped ping — devcontainer not on tailnet"
fi

diag_section "4. TCP connect"
port_part="$(echo "$URL" | sed -E 's|.*:([0-9]+)/?$|\1|')"
[[ "$port_part" == "$URL" ]] && port_part="$PORT"
if command -v nc >/dev/null 2>&1; then
  if nc -zv -w 5 "$host_part" "$port_part" 2>&1; then
    diag_ok "TCP ${host_part}:${port_part} open"
  else
    record_fail
    diag_fail "TCP connect failed — nothing listening or ACL blocks port"
  fi
elif command -v curl >/dev/null 2>&1; then
  diag_info "nc not available; using curl connect timeout"
else
  diag_warn "Skipped TCP check"
fi

diag_section "5. HTTP(S) request"
diag_info "curl -kI ${URL}"
if curl -kfsSI --connect-timeout 15 --max-time 30 "$URL" 2>&1; then
  diag_ok "HTTP(S) response received"
else
  record_fail
  diag_fail "HTTP(S) request failed"
  diag_info "If TCP works but HTTPS fails: missing tailscale serve, wrong backend port, or cert issue"
  diag_info "If using HTTP only: retry with --http"
fi

diag_section "6. Compare with sidecar serve status"
diag_info "On the sidecar container run: tailscale serve status"
diag_info "Expected: HTTPS proxy to app on 0.0.0.0 (not 127.0.0.1 unless shared netns)"

diag_section "Summary"
[ "$FAILED" -eq 0 ] && diag_ok "Tailnet URL checks passed" || diag_fail "Tailnet URL checks failed"
exit "$FAILED"
