#!/usr/bin/env bash
# Audit container mounts — detect bind mounts replaced by named volumes (Coolify bug).
#
# Usage:
#   audit-volumes.sh [container-name-filter]
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

TARGET="${1:-}"

[[ "${1:-}" == "-h" || "${1:-}" == "--help" ]] && {
  sed -n '2,5p' "$0" | sed 's/^# \?//'
  exit 0
}

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

WARN=0
for c in $CONTAINERS; do
  diag_section_b "$c"
  while IFS='|' read -r type src dst; do
    [[ -z "$type" ]] && continue
    if [[ "$type" == "bind" ]]; then
      if [ -n "${COOLIFY_DOCKER_HOST:-}" ]; then
        if devops_ssh "${COOLIFY_DOCKER_HOST}" "[ -e '${src}' ]"; then
          echo "  [bind]   ${src} -> ${dst}  (exists on host)"
        else
          echo "  [bind]   ${src} -> ${dst}  *** HOST PATH MISSING ***"
          WARN=1
        fi
      elif [[ -e "$src" ]]; then
        echo "  [bind]   ${src} -> ${dst}  (exists on host)"
      else
        echo "  [bind]   ${src} -> ${dst}  *** HOST PATH MISSING ***"
        WARN=1
      fi
    elif [[ "$type" == "volume" ]]; then
      echo "  [volume] ${src} -> ${dst}  (named volume — not a host bind path)"
    else
      echo "  [${type}] ${src} -> ${dst}"
    fi
  done < <(docker inspect "$c" --format '{{range .Mounts}}{{.Type}}|{{.Source}}|{{.Destination}}
{{end}}')
done

printf '\n'
if [ "$WARN" -eq 1 ]; then
  diag_warn "Bind mount issues detected — check Coolify Storages tab and redeploy"
  exit 1
fi

diag_ok "Volume audit complete"
exit 0
