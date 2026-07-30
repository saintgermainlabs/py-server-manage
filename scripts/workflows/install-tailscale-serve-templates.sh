#!/usr/bin/env bash
# Sync Tailscale serve templates to a common host location and render per-app configs.
#
# Installs repo templates to a shared directory on the Coolify host so every
# tailscale sidecar can bind-mount its app subdirectory.
#
# Usage:
#   install-tailscale-serve-templates.sh --tailnet tiger-bushmaster.ts.net
#   install-tailscale-serve-templates.sh --tailnet example.ts.net --profile openclaw --profile vault
#   COOLIFY_DOCKER_HOST=dom@coolify install-tailscale-serve-templates.sh --tailnet example.ts.net --profile openclaw
#
# Host layout (default /opt/tailscale/serve):
#   templates/          # synced from repo (reference)
#   openclaw/serve.json # rendered per profile
#   vault/serve.json
#
# Environment:
#   TAILSCALE_SERVE_HOST_ROOT  Install root (default: /opt/tailscale/serve)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
RENDER="${SCRIPT_DIR}/render-tailscale-serve-config.sh"
# shellcheck source=../diagnostics/lib/common.sh
source "${REPO_ROOT}/scripts/diagnostics/lib/common.sh"

HOST_ROOT="${TAILSCALE_SERVE_HOST_ROOT:-/opt/tailscale/serve}"
TAILNET=""
PROFILES=()
ASSUME_YES=false
TAILNET_ENV="${REPO_ROOT}/templates/tailscale/tailnet.env"

if [ -f "$TAILNET_ENV" ]; then
  # shellcheck disable=SC1090
  source "$TAILNET_ENV"
  HOST_ROOT="${TAILSCALE_SERVE_HOST_ROOT:-$HOST_ROOT}"
fi

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \?//'
  exit 0
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --host-root) HOST_ROOT="$2"; shift 2 ;;
    --tailnet) TAILNET="$2"; shift 2 ;;
    --profile) PROFILES+=("$2"); shift 2 ;;
    -y|--yes) ASSUME_YES=true; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

[ -n "$TAILNET" ] || { diag_fail "Missing --tailnet (or set TAILNET in templates/tailscale/tailnet.env)"; exit 1; }

if [ "${#PROFILES[@]}" -eq 0 ]; then
  while IFS= read -r -d '' f; do
    base="$(basename "$f" .env)"
    [ "$base" = example ] && continue
    PROFILES+=("$base")
  done < <(find "${REPO_ROOT}/templates/tailscale/profiles" -maxdepth 1 -name '*.env' -print0)
fi

[ "${#PROFILES[@]}" -gt 0 ] || { diag_fail "No profiles to install"; exit 1; }

diag_section "Install Tailscale serve templates"
diag_info "Host root: ${HOST_ROOT}"
diag_info "Tailnet: ${TAILNET}"
diag_info "Profiles: ${PROFILES[*]}"
if [ -n "${COOLIFY_DOCKER_HOST:-}" ]; then
  diag_info "Remote host: ${COOLIFY_DOCKER_HOST}"
fi

confirm_or_abort "Create/update ${HOST_ROOT} on Docker host? [y/N] " "$ASSUME_YES" || {
  diag_info "Aborted"
  exit 0
}

run_on_docker_host "mkdir -p '${HOST_ROOT}/templates'"

# Sync template files to host (tar over ssh for simplicity, no rsync dependency)
tar -C "${REPO_ROOT}/templates/tailscale" -cf - \
  serve.json.template serve.modern.json.template tailnet.env profiles \
  | run_on_docker_host "tar -C '${HOST_ROOT}/templates' -xf -"

diag_ok "Synced templates to ${HOST_ROOT}/templates/"

for profile in "${PROFILES[@]}"; do
  diag_section "Render profile: ${profile}"
  rendered="$(bash "$RENDER" --profile "$profile" --tailnet "$TAILNET")"
  app_dir="${HOST_ROOT}/${profile}"
  run_on_docker_host "mkdir -p '${app_dir}'"
  tmp="$(mktemp)"
  printf '%s\n' "$rendered" >"$tmp"
  bash "$RENDER" --validate "$tmp"
  if [ -n "${COOLIFY_DOCKER_HOST:-}" ]; then
    devops_ssh "${COOLIFY_DOCKER_HOST}" "mkdir -p '${app_dir}' && cat > '${app_dir}/serve.json'" <"$tmp"
  else
    cp "$tmp" "${app_dir}/serve.json"
  fi
  rm -f "$tmp"
  run_on_docker_host "chown -R 1000:1000 '${app_dir}' 2>/dev/null || true"
  diag_ok "Wrote ${app_dir}/serve.json"
done

cat <<NOTE

Next steps (per Coolify service):

  1. Coolify → Service → Storages → add directory mount:
       Host: ${HOST_ROOT}/<app>
       Container: /config/serve

  2. Environment on tailscale sidecar:
       TS_SERVE_CONFIG=/config/serve/serve.json
       TS_HOSTNAME=<app>

  3. Compose: app uses network_mode: "service:tailscale"

  4. Redeploy sidecar (or restart) and verify:
       docker exec tailscale-<id> tailscale serve status
       docker exec tailscale-<id> ss -tlnp | grep -E '443|8080'

Doc: docs/tailscale/serve-config-templates.md
NOTE
