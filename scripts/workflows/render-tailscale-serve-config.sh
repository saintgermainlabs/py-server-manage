#!/usr/bin/env bash
# Render a Tailscale serve.json from repo templates for TS_SERVE_CONFIG.
#
# Usage:
#   render-tailscale-serve-config.sh --profile openclaw --tailnet tiger-bushmaster.ts.net
#   render-tailscale-serve-config.sh --app vault --port 8200 --hostname vault --tailnet example.ts.net -o /opt/tailscale/serve/vault/serve.json
#   render-tailscale-serve-config.sh --profile openclaw --tailnet example.ts.net --format modern
#
# Environment:
#   TAILSCALE_SERVE_HOST_ROOT  Default host install root (/opt/tailscale/serve)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
TEMPLATE_DIR="${REPO_ROOT}/templates/tailscale"
PROFILE_DIR="${TEMPLATE_DIR}/profiles"
DEFAULT_HOST_ROOT="${TAILSCALE_SERVE_HOST_ROOT:-/opt/tailscale/serve}"

APP_NAME=""
HOSTNAME=""
PORT=""
BACKEND_HOST="127.0.0.1"
TAILNET=""
PROFILE=""
OUTPUT=""
FORMAT="legacy"
HOST_INSTALL=false
VALIDATE_ONLY=false

usage() {
  cat <<'EOF'
Render Tailscale serve.json for TS_SERVE_CONFIG (Coolify sidecar mounts).

Options:
  --profile NAME       Load templates/tailscale/profiles/NAME.env
  --app NAME           Service name (svc:NAME); defaults to profile APP_NAME or HOSTNAME
  --hostname NAME      MagicDNS label (TS_HOSTNAME); defaults to --app
  --port PORT          Backend port inside shared netns (required unless in profile)
  --backend-host HOST  Backend host (default: 127.0.0.1 for network_mode: service:tailscale)
  --tailnet DOMAIN     Tailnet DNS suffix, e.g. tiger-bushmaster.ts.net (required)
  --format legacy|modern
                       legacy = TS_SERVE_CONFIG auto-load (default)
                       modern = tailscale serve set-config format (v0.0.1)
  -o, --output PATH    Write file (default: stdout)
  --host-install       Write to ${TAILSCALE_SERVE_HOST_ROOT}/<app>/serve.json
  --validate PATH      Validate an existing serve.json and exit
  -h, --help

Examples:
  bash scripts/workflows/render-tailscale-serve-config.sh \
    --profile openclaw --tailnet tiger-bushmaster.ts.net --host-install

  bash scripts/workflows/render-tailscale-serve-config.sh \
    --app vault --port 8200 --hostname vault --tailnet example.ts.net \
    -o /opt/tailscale/serve/vault/serve.json
EOF
  exit "${1:-0}"
}

load_profile() {
  local name="$1"
  local file="${PROFILE_DIR}/${name}.env"
  [ -f "$file" ] || { echo "Profile not found: $file" >&2; exit 1; }
  # shellcheck disable=SC1090
  source "$file"
}

substitute_template() {
  local template="$1"
  local fqdn="${HOSTNAME}.${TAILNET}:443"
  local backend_url="http://${BACKEND_HOST}:${PORT}"
  sed \
    -e "s/{{APP_NAME}}/${APP_NAME}/g" \
    -e "s/{{FQDN}}/${fqdn}/g" \
    -e "s|{{BACKEND_URL}}|${backend_url}|g" \
    "$template"
}

validate_serve_json() {
  local file="$1"
  [ -f "$file" ] || { echo "FAIL: file not found: $file" >&2; return 1; }

  local failed=0
  if ! python3 -m json.tool "$file" >/dev/null 2>&1; then
    echo "FAIL: invalid JSON: $file" >&2
    return 1
  fi

  if python3 - "$file" <<'PY' 2>/dev/null; then
    :
  else
    echo "FAIL: serve TCP listener uses port 8080 — use HTTPS on 443 only" >&2
    failed=1
  fi
import json, sys
path = sys.argv[1]
with open(path) as f:
    data = json.load(f)
tcp = data.get("TCP") or {}
for svc in data.get("Services", {}).values():
    if isinstance(svc, dict) and "TCP" in svc:
        tcp = {**tcp, **svc["TCP"]}
if "8080" in tcp:
    sys.exit(1)
sys.exit(0)
PY

  if grep -q '"443"' "$file" || grep -q 'tcp:443' "$file" || grep -q 'TS_CERT_DOMAIN' "$file"; then
    echo "OK: listener uses port 443"
  else
    echo "WARN: no port 443 listener found in $file" >&2
  fi

  if grep -qE '"Proxy"[[:space:]]*:[[:space:]]*"http://' "$file"; then
    echo "OK: backend proxy target present"
  else
    echo "WARN: no HTTP Proxy backend found" >&2
  fi

  return "$failed"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --profile) PROFILE="$2"; shift 2 ;;
    --app) APP_NAME="$2"; shift 2 ;;
    --hostname) HOSTNAME="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --backend-host) BACKEND_HOST="$2"; shift 2 ;;
    --tailnet) TAILNET="$2"; shift 2 ;;
    --format) FORMAT="$2"; shift 2 ;;
    -o|--output) OUTPUT="$2"; shift 2 ;;
    --host-install) HOST_INSTALL=true; shift ;;
    --validate) VALIDATE_ONLY=true; OUTPUT="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown option: $1" >&2; usage 2 ;;
  esac
done

if [ "$VALIDATE_ONLY" = true ]; then
  validate_serve_json "$OUTPUT"
  exit $?
fi

[ -n "$PROFILE" ] && load_profile "$PROFILE"

APP_NAME="${APP_NAME:-${HOSTNAME:-}}"
HOSTNAME="${HOSTNAME:-$APP_NAME}"
PORT="${PORT:-}"

[ -n "$APP_NAME" ] || { echo "Missing --app or --profile" >&2; exit 1; }
[ -n "$PORT" ] || { echo "Missing --port or PORT in profile" >&2; exit 1; }
[ -n "$TAILNET" ] || { echo "Missing --tailnet (e.g. tiger-bushmaster.ts.net)" >&2; exit 1; }

case "$FORMAT" in
  legacy)  TEMPLATE="${TEMPLATE_DIR}/serve.json.template" ;;
  modern)  TEMPLATE="${TEMPLATE_DIR}/serve.modern.json.template" ;;
  *) echo "Unknown format: $FORMAT (use legacy or modern)" >&2; exit 1 ;;
esac

[ -f "$TEMPLATE" ] || { echo "Template missing: $TEMPLATE" >&2; exit 1; }

if [ "$HOST_INSTALL" = true ]; then
  OUTPUT="${DEFAULT_HOST_ROOT}/${APP_NAME}/serve.json"
fi

rendered="$(substitute_template "$TEMPLATE")"

if [ -n "$OUTPUT" ]; then
  mkdir -p "$(dirname "$OUTPUT")"
  printf '%s\n' "$rendered" >"$OUTPUT"
  validate_serve_json "$OUTPUT" || exit 1
  echo "Wrote ${OUTPUT}"
  echo "Mount in compose:"
  echo "  TS_SERVE_CONFIG=/config/serve/serve.json"
  echo "  volumes:"
  echo "    - $(dirname "$OUTPUT"):/config/serve:ro"
else
  printf '%s\n' "$rendered"
fi
