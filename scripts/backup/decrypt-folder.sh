#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'usage: %s [-f] <encrypted-folder> <output-folder>\n' "$(basename "$0")" >&2
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

if [ "$#" -ne 2 ]; then
  usage
fi

source_dir="$1"
output_dir="$2"

if ! command -v gpg >/dev/null 2>&1; then
  printf 'gpg is required\n' >&2
  exit 1
fi

if [ ! -d "$source_dir" ]; then
  printf 'encrypted folder not found: %s\n' "$source_dir" >&2
  exit 1
fi

source_abs="$(CDPATH= cd -- "$source_dir" && pwd)"
mkdir -p "$output_dir"
output_abs="$(CDPATH= cd -- "$output_dir" && pwd)"

if [ "$source_abs" = "$output_abs" ]; then
  printf 'encrypted and output folders must be different\n' >&2
  exit 1
fi

find "$source_abs" -type f -name '*.gpg' -print0 | while IFS= read -r -d '' file; do
  rel="${file#"$source_abs/"}"
  rel="${rel%.gpg}"
  dest="$output_abs/$rel"
  mkdir -p "$(dirname -- "$dest")"

  if [ -e "$dest" ] && [ "$force" -ne 1 ]; then
    printf 'refusing to overwrite: %s\n' "$dest" >&2
    exit 1
  fi

  tmp="$dest.tmp"
  rm -f -- "$tmp"
  gpg --batch --yes --decrypt --output "$tmp" "$file"
  mv -- "$tmp" "$dest"
  printf 'decrypted: %s -> %s\n' "$file" "$dest"
done
