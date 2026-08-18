# Least-privilege policy for the backup host Vault Agent.
# Apply after Vault is unsealed:
#   vault policy write server-backup deploy/vault/policies/server-backup.hcl

path "secret/data/py-server-manage/backup/borg" {
  capabilities = ["read"]
}

path "secret/metadata/py-server-manage/backup/borg" {
  capabilities = ["read"]
}

path "secret/data/py-server-manage/backup/databases/*" {
  capabilities = ["read"]
}

path "secret/metadata/py-server-manage/backup/databases/*" {
  capabilities = ["list", "read"]
}

path "auth/token/renew-self" {
  capabilities = ["update"]
}

path "auth/token/lookup-self" {
  capabilities = ["read"]
}
