#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [-f] <source-folder> <output-folder> <recipient>\n' "$(basename "$0")" >&2
  exit 2
}

force=0

while getopts ':f' opt; do
  case "$opt" in
    f) force=1 ;;
    *) usage ;;
  esac
done
shift $((OPTIND - 1))

if [ "$#" -ne 3 ]; then
  usage
fi

source_dir="$1"
output_dir="$2"
recipient="$3"

if ! command -v gpg >/dev/null 2>&1; then
  printf 'gpg is required\n' >&2
  exit 1
fi

if [ ! -d "$source_dir" ]; then
  printf 'source folder not found: %s\n' "$source_dir" >&2
  exit 1
fi

source_abs="$(CDPATH= cd -- "$source_dir" && pwd)"
mkdir -p "$output_dir"
output_abs="$(CDPATH= cd -- "$output_dir" && pwd)"

if [ "$source_abs" = "$output_abs" ]; then
  printf 'source and output folders must be different\n' >&2
  exit 1
fi

if ! gpg --list-keys "$recipient" >/dev/null 2>&1; then
  printf 'recipient key not found: %s\n' "$recipient" >&2
  exit 1
fi

find "$source_abs" -type f -print0 | while IFS= read -r -d '' file; do
  rel="${file#"$source_abs/"}"
  dest="$output_abs/$rel.gpg"
  mkdir -p "$(dirname -- "$dest")"

  if [ -e "$dest" ] && [ "$force" -ne 1 ]; then
    printf 'refusing to overwrite: %s\n' "$dest" >&2
    exit 1
  fi

  tmp="$dest.tmp"
  rm -f -- "$tmp"
  gpg --batch --yes --trust-model always --recipient "$recipient" --encrypt --output "$tmp" "$file"
  mv -- "$tmp" "$dest"
  printf 'encrypted: %s -> %s\n' "$file" "$dest"
done
