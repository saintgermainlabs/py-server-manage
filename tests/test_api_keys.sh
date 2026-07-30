for var in \
  TAILSCALE_API_KEY \
  TAILSCALE_OAUTH_CLIENT_ID \
  TAILSCALE_OAUTH_CLIENT_SECRET
do
  value="${!var:-}"
  if [[ -n "$value" ]]; then
    printf '%s: set (%s characters)\n' "$var" "${#value}"
  else
    printf '%s: not set\n' "$var"
  fi
done