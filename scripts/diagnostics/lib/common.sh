#!/usr/bin/env bash
# Shared helpers for diagnostic scripts.
set -euo pipefail

diag_section() {
  printf '\n--- %s ---\n' "$1"
}

diag_ok() {
  printf 'OK: %s\n' "$*"
}

diag_warn() {
  printf 'WARN: %s\n' "$*" >&2
}

diag_fail() {
  printf 'FAIL: %s\n' "$*" >&2
}

diag_info() {
  printf '    %s\n' "$*"
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    diag_fail "docker CLI not found"
    return 1
  fi
}

# Use remote Docker context when COOLIFY_DOCKER_HOST is set (local profile).
ensure_docker_context() {
  ensure_docker || return 1
  local script
  script="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/.devcontainer/scripts/docker-devops-use.sh"
  if [ -n "${COOLIFY_DOCKER_HOST:-}" ] && [ -x "$script" ]; then
    bash "$script" remote >/dev/null 2>&1 || true
    return 0
  fi
  if [ -n "${COOLIFY_DOCKER_HOST:-}" ] && command -v docker_remote_use >/dev/null 2>&1; then
    docker_remote_use "${COOLIFY_DOCKER_HOST}" >/dev/null 2>&1 || true
  fi
}

container_running() {
  local name="$1"
  docker ps --format '{{.Names}}' | grep -qx "$name"
}

container_exists() {
  local name="$1"
  docker ps -a --format '{{.Names}}' | grep -qx "$name"
}

# Find first running container matching a grep pattern (extended regex).
find_container() {
  local pattern="$1"
  docker ps --format '{{.Names}}' | grep -Ei "$pattern" | head -1
}

# Run a command inside a container; tolerate missing tools.
docker_exec() {
  local container="$1"
  shift
  docker exec "$container" "$@" 2>/dev/null
}

# curl/wget inside container
docker_http_head() {
  local container="$1"
  local url="$2"
  docker_exec "$container" curl -fsSI "$url" \
    || docker_exec "$container" wget --spider -S "$url" 2>&1 \
    || return 1
}

# Resolve Coolify sidecar from app using network_mode: service:<sidecar>.
# Sets SIDECAR_ID and SIDECAR_NAME when found; returns 0 on match.
resolve_sidecar_from_app() {
  local app="$1"
  local netmode
  netmode="$(docker inspect "$app" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true)"
  if [[ "$netmode" == container:* ]]; then
    SIDECAR_ID="${netmode#container:}"
    SIDECAR_NAME="$(docker inspect "$SIDECAR_ID" --format '{{.Name}}' 2>/dev/null | sed 's#^/##')"
    return 0
  fi
  return 1
}

# Coolify often names sidecar tailscale-<stack-id>; app may be on bridge network.
resolve_sidecar_for_stack() {
  local app="$1"
  local suffix=""
  suffix="$(echo "$app" | sed -n 's/.*-\([a-z0-9]\{25,\}\)$/\1/p')"
  if [ -n "$suffix" ]; then
    local ts_name="tailscale-${suffix}"
    if container_running "$ts_name"; then
      SIDECAR_NAME="$ts_name"
      SIDECAR_ID="$(docker inspect "$ts_name" --format '{{.Id}}' 2>/dev/null | cut -c1-12)"
      return 0
    fi
  fi
  return 1
}

# Detect split network namespace: sidecar has tailscale0 but no eth0 / no default route.
sidecar_netns_split() {
  local sidecar="$1"
  local links routes
  links="$(docker_exec "$sidecar" ip link 2>/dev/null || true)"
  routes="$(docker_exec "$sidecar" ip route 2>/dev/null || true)"
  if echo "$links" | grep -q 'eth0'; then
    return 1
  fi
  if echo "$links" | grep -q 'tailscale0' && [ -z "$routes" ]; then
    return 0
  fi
  return 1
}

# SSH to the Coolify host using the devcontainer dedicated key (~/.ssh/config).
devops_ssh() {
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$@"
}

# Run a shell command on the Docker host filesystem (not inside a container).
# Uses SSH when COOLIFY_DOCKER_HOST is set (local devcontainer profile).
run_on_docker_host() {
  local cmd="$1"
  if [ -n "${COOLIFY_DOCKER_HOST:-}" ]; then
    devops_ssh "${COOLIFY_DOCKER_HOST}" "$cmd"
  else
    bash -c "$cmd"
  fi
}

# Pretty output (optional, for Coolify toolkit scripts)
diag_ok_b()   { printf '  \033[32m[OK]\033[0m   %s\n' "$*"; }
diag_warn_b() { printf '  \033[33m[WARN]\033[0m %s\n' "$*" >&2; }
diag_fail_b() { printf '  \033[31m[FAIL]\033[0m %s\n' "$*" >&2; }
diag_section_b() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

confirm_or_abort() {
  local prompt="$1"
  local assume_yes="${2:-false}"
  if [ "$assume_yes" = true ] || [ "${ASSUME_YES:-false}" = true ]; then
    return 0
  fi
  read -r -p "$prompt" answer
  [[ "$answer" =~ ^[Yy]$ ]]
}
