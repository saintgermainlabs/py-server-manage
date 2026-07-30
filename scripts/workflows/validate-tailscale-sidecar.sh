#!/usr/bin/env bash
# Validate Docker Compose files that include Tailscale sidecars.
set -euo pipefail

usage() {
  printf 'usage: %s [--require-serve-script] <docker-compose.yml>\n' "$(basename "$0")" >&2
  exit 2
}

REQUIRE_SERVE=false
COMPOSE_FILE=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --require-serve-script) REQUIRE_SERVE=true; shift ;;
    -h|--help) usage ;;
    *)
      COMPOSE_FILE="$1"
      shift
      ;;
  esac
done

[ -n "$COMPOSE_FILE" ] || usage
[ -f "$COMPOSE_FILE" ] || { echo "File not found: $COMPOSE_FILE" >&2; exit 1; }

FAILED=0
warn() { printf 'WARN: %s\n' "$*" >&2; }
fail() { printf 'FAIL: %s\n' "$*" >&2; FAILED=1; }
ok() { printf 'OK: %s\n' "$*"; }

if ! command -v docker >/dev/null 2>&1; then
  fail "docker CLI not found"
else
  if docker compose -f "$COMPOSE_FILE" config >/dev/null 2>&1; then
    ok "compose syntax valid"
  else
    fail "compose syntax invalid"
  fi
fi

if grep -qi 'tailscale/tailscale' "$COMPOSE_FILE"; then
  ok "Tailscale sidecar image referenced"

  if grep -qE 'TS_AUTHKEY|TS_AUTH_KEY' "$COMPOSE_FILE"; then
    ok "TS_AUTHKEY referenced"
  else
    warn "No TS_AUTHKEY env var found — sidecar may not join tailnet"
  fi

  if grep -q 'TS_STATE_DIR\|/var/lib/tailscale' "$COMPOSE_FILE"; then
    ok "Tailscale state volume/dir present"
  else
    warn "No persistent TS state — node identity may reset on redeploy"
  fi

  if grep -q 'NET_ADMIN\|/dev/net/tun' "$COMPOSE_FILE"; then
    ok "TUN capabilities/devices configured"
  else
    warn "Missing NET_ADMIN or /dev/net/tun — sidecar may fail"
  fi

  if grep -q 'TS_SERVE_CONFIG' "$COMPOSE_FILE"; then
    ok "TS_SERVE_CONFIG referenced"
    if grep -qE 'TS_SERVE_CONFIG=.*/[^/]+\.json' "$COMPOSE_FILE"; then
      if grep -qE '/config/serve[^/]|/config/serve:' "$COMPOSE_FILE"; then
        ok "serve config uses directory mount pattern (/config/serve/)"
      else
        warn "TS_SERVE_CONFIG points at a file path — prefer directory mount (see docs/tailscale/serve-config-templates.md)"
      fi
    fi
  else
    warn "No TS_SERVE_CONFIG — serve must be set via CLI or entrypoint (see docs/tailscale/serve-config-templates.md)"
  fi

  if grep -q 'network_mode:.*service:tailscale\|network_mode:.*service:<tailscale>' "$COMPOSE_FILE"; then
    ok "App uses network_mode: service:tailscale (shared netns)"
  elif grep -q 'network_mode:.*container:' "$COMPOSE_FILE"; then
    warn "network_mode: container:<app> detected — prefer app joins sidecar (service:tailscale)"
  fi

  if [ "$REQUIRE_SERVE" = true ]; then
    if grep -qi 'tailscale serve' "$COMPOSE_FILE"; then
      ok "tailscale serve referenced in compose/entrypoint"
    else
      fail "No tailscale serve in compose — add entrypoint (see docs/workflows/tailscale-serve-https.md)"
    fi
  else
    warn "Remember to run 'tailscale serve' after deploy for HTTPS (see docs/workflows/tailscale-serve-https.md)"
  fi
else
  ok "No Tailscale sidecar detected — nothing to validate"
fi

exit "$FAILED"
