#!/usr/bin/env bash
# Bootstrap shared Tailscale serve configs on the Coolify Docker host.
#
# Renders every profile in templates/tailscale/profiles/ (except example) to
# /opt/tailscale/serve/<app>/serve.json so each sidecar can mount one directory.
#
# Usage:
#   bash scripts/workflows/setup-tailscale-serve-host.sh
#   bash scripts/workflows/setup-tailscale-serve-host.sh --yes --profile openclaw
#   COOLIFY_DOCKER_HOST=dom@ubuntu bash scripts/workflows/setup-tailscale-serve-host.sh --yes
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL="${SCRIPT_DIR}/install-tailscale-serve-templates.sh"
TAILNET_ENV="$(cd "${SCRIPT_DIR}/../.." && pwd)/templates/tailscale/tailnet.env"

TAILNET=""
EXTRA=()

while [ "$#" -gt 0 ]; do
  case "$1" in
    --tailnet) TAILNET="$2"; shift 2 ;;
    *) EXTRA+=("$1"); shift ;;
  esac
done

if [ -z "$TAILNET" ] && [ -f "$TAILNET_ENV" ]; then
  # shellcheck disable=SC1090
  source "$TAILNET_ENV"
fi

[ -n "$TAILNET" ] || {
  echo "Set TAILNET in templates/tailscale/tailnet.env or pass --tailnet" >&2
  exit 1
}

exec bash "$INSTALL" --tailnet "$TAILNET" "${EXTRA[@]}"
