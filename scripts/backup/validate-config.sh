#!/usr/bin/env bash
set -euo pipefail

project_dir="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

bash -n "$project_dir"/scripts/*.sh

for profile in local production; do
  config="$project_dir/resticprofile/$profile.yaml"
  if [ ! -f "$config" ]; then
    printf 'missing config: %s\n' "$config" >&2
    exit 1
  fi

  for required in 'version: "1"' "$profile:" 'repository: "${RESTIC_REPOSITORY}"' 'password-file: "${RESTIC_PASSWORD_FILE}"' 'backup:' 'retention:' 'check:'; do
    if ! grep -Fq -- "$required" "$config"; then
      printf 'config %s is missing required entry: %s\n' "$config" "$required" >&2
      exit 1
    fi
  done

  printf 'config ok: %s\n' "$config"
done

"$project_dir/scripts/verify-tools.sh"
