#!/usr/bin/env bash
set -euo pipefail

missing=0

for tool in restic resticprofile gpg ssh sftp; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    printf 'missing: %s\n' "$tool" >&2
    missing=1
  else
    printf 'found: %s (%s)\n' "$tool" "$(command -v "$tool")"
  fi
done

if [ "$missing" -ne 0 ]; then
  exit 1
fi
