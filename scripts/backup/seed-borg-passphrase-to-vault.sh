#!/usr/bin/env bash
# Copy BORG_PASSPHRASE from /etc/server-backup/credentials.env into Vault KV.
# Never prints the passphrase. Requires Vault unsealed and a token file.
#
# Usage (on the Coolify host, as a user in the docker group):
#   VAULT_TOKEN_FILE=/home/dom/.vault-token-seed \
#     ./scripts/backup/seed-borg-passphrase-to-vault.sh
set -euo pipefail

CREDS="${CREDENTIALS_ENV:-/etc/server-backup/credentials.env}"
TOKEN_FILE="${VAULT_TOKEN_FILE:-/home/dom/.vault-token-seed}"
VAULT_ADDR="${VAULT_ADDR:-https://vault.tiger-bushmaster.ts.net}"
KV_PATH="${VAULT_BORG_PATH:-secret/py-server-manage/backup/borg}"

if [[ ! -r "$TOKEN_FILE" ]]; then
  echo "missing readable token file: $TOKEN_FILE" >&2
  exit 1
fi

if [[ ! -e "$CREDS" ]]; then
  echo "missing credentials file: $CREDS (docker can still bind-mount it)" >&2
fi

docker run --rm --network host \
  -e VAULT_ADDR="$VAULT_ADDR" \
  -v "$TOKEN_FILE:/token:ro" \
  -v "$CREDS:/creds.env:ro" \
  --entrypoint /bin/sh \
  hashicorp/vault:1.17 \
  -ec '
    set -eu
    export VAULT_TOKEN="$(tr -d "[:space:]" < /token)"
    if ! vault status >/dev/null; then
      echo "Vault is sealed or unreachable; unseal first." >&2
      exit 2
    fi
    set -a
    # shellcheck disable=SC1091
    . /creds.env
    set +a
    if [ -z "${BORG_PASSPHRASE:-}" ]; then
      echo "BORG_PASSPHRASE missing in credentials.env" >&2
      exit 3
    fi
    vault kv put "'"$KV_PATH"'" passphrase="$BORG_PASSPHRASE" >/dev/null
    echo "wrote kv path '"$KV_PATH"' field=passphrase (value not printed)"
  '
