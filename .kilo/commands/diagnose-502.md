Diagnose the reported 502 without changing infrastructure.

Establish the request path:

client -> Cloudflare -> origin/Tailscale -> reverse proxy -> container

Check, where access permits:

- DNS resolution
- Cloudflare proxy and SSL mode
- origin reachability
- listening ports
- Docker container state and health
- recent application and proxy logs
- Compose networks and labels
- certificate and hostname mismatch
- Tailscale status when applicable

Redact credentials and tokens.

Return:

1. observed evidence
2. most likely failure boundary
3. ranked causes
4. exact safe verification commands
5. proposed remediation requiring approval
