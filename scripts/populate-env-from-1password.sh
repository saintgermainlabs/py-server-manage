#!/usr/bin/env bash
set -euo pipefail

usage() {
    printf 'usage: %s [--env-file <path>] KEY=op://vault/item/field [KEY=op://vault/item/field ...]\n' "$(basename "$0")" >&2
    printf 'example: %s COOLIFY_TOKEN=op://DevOps/Coolify/token OP_SERVICE_ACCOUNT_TOKEN=op://DevOps/1Password/token\n' "$(basename "$0")" >&2
    exit 2
}

shell_quote() {
    local value="$1"
    printf "'%s'" "${value//\'/\'\\\'\'}"
}

set_env_value() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    local quoted
    local tmp

    quoted="$(shell_quote "$value")"
    tmp="$(mktemp)"

    if grep -Eq "^[[:space:]]*#?[[:space:]]*${key}[[:space:]]*=" "$env_file"; then
        awk -v key="$key" -v value="$quoted" '
            BEGIN { updated = 0 }
            {
                line = $0
                if (line ~ "^[[:space:]]*#?[[:space:]]*" key "[[:space:]]*=") {
                    print key "=" value
                    updated = 1
                } else {
                    print line
                }
            }
            END { if (!updated) print key "=" value }
        ' "$env_file" > "$tmp"
    else
        cat "$env_file" > "$tmp"
        printf '\n%s=%s\n' "$key" "$quoted" >> "$tmp"
    fi

    cat "$tmp" > "$env_file"
    rm -f "$tmp"
}

env_file=".env"
assignments=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --env-file)
            [ "$#" -ge 2 ] || usage
            env_file="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *=*)
            assignments+=("$1")
            shift
            ;;
        *)
            usage
            ;;
    esac
done

[ "${#assignments[@]}" -gt 0 ] || usage

if ! command -v op >/dev/null 2>&1; then
    printf 'op CLI is required\n' >&2
    exit 1
fi

if ! op whoami >/dev/null 2>&1; then
    printf '1Password CLI is not authenticated. Sign in first with: eval $(op signin)\n' >&2
    exit 1
fi

if [ ! -f "$env_file" ]; then
    if [ -f ".env.example" ]; then
        cp ".env.example" "$env_file"
    else
        touch "$env_file"
    fi
fi

chmod 600 "$env_file"

for assignment in "${assignments[@]}"; do
    key="${assignment%%=*}"
    ref="${assignment#*=}"

    if [[ ! "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
        printf 'invalid env key: %s\n' "$key" >&2
        exit 1
    fi

    if [[ ! "$ref" == op://* ]]; then
        printf 'invalid 1Password reference for %s: %s\n' "$key" "$ref" >&2
        exit 1
    fi

    value="$(op read "$ref")"
    set_env_value "$env_file" "$key" "$value"
    printf 'updated %s from 1Password\n' "$key"
done

printf 'done: %s\n' "$env_file"
