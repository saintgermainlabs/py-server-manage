#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s <local|production> <resticprofile-command> [args...]\n' "$(basename "$0")" >&2
  exit 2
}

if [ "$#" -lt 2 ]; then
  usage
fi

environment="$1"
shift

script_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
project_dir="$(dirname "$script_dir")"
env_file="$project_dir/env/$environment.env"
example_env_file="$project_dir/env/$environment.env.example"
config_file="$project_dir/resticprofile/$environment.yaml"

case "$environment" in
  local|production) ;;
  *) usage ;;
esac

if [ ! -f "$env_file" ]; then
  printf 'environment file not found: %s\n' "$env_file" >&2
  printf 'copy and edit: %s\n' "$example_env_file" >&2
  exit 1
fi

if [ ! -f "$config_file" ]; then
  printf 'resticprofile config not found: %s\n' "$config_file" >&2
  exit 1
fi

set -a
. "$env_file"
set +a

export RESTICPROFILE_CONFIG="${RESTICPROFILE_CONFIG:-$config_file}"

exec resticprofile --config "$RESTICPROFILE_CONFIG" --name "$environment" "$@"
