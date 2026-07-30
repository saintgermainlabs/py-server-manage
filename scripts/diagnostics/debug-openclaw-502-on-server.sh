#!/usr/bin/env bash
# Run ON the Coolify Docker host (local docker socket).
# Diagnose OpenClaw tailnet 502 and optionally reapply tailscale serve.
#
# Usage on server:
#   bash debug-openclaw-502-on-server.sh
#   bash debug-openclaw-502-on-server.sh --apply-fix
#
# From devcontainer:
#   ssh ubuntu 'bash -s -- --apply-fix' < scripts/diagnostics/debug-openclaw-502-on-server.sh
set -uo pipefail

APPLY_FIX=false
APP_CONT="${OPENCLAW_APP_CONTAINER:-openclaw-z9rqy3p5e57o4u4kxexeflbg}"
SIDE_CONT="${OPENCLAW_SIDECAR_CONTAINER:-tailscale-z9rqy3p5e57o4u4kxexeflbg}"
APP_PORT="${OPENCLAW_APP_PORT:-8888}"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --apply-fix) APPLY_FIX=true; shift ;;
    --app) APP_CONT="$2"; shift 2 ;;
    --sidecar) SIDE_CONT="$2"; shift 2 ;;
    *) shift ;;
  esac
done

echo "=== OpenClaw tailnet 502 diagnostic ==="

app_state="$(docker inspect "$APP_CONT" --format '{{.State.Status}}' 2>/dev/null || echo missing)"
side_state="$(docker inspect "$SIDE_CONT" --format '{{.State.Status}}' 2>/dev/null || echo missing)"
side_restarts="$(docker inspect "$SIDE_CONT" --format '{{.RestartCount}}' 2>/dev/null || echo 0)"
app_netmode="$(docker inspect "$APP_CONT" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || echo unknown)"
side_netmode="$(docker inspect "$SIDE_CONT" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || echo unknown)"

echo "App: ${APP_CONT} state=${app_state} NetworkMode=${app_netmode}"
echo "Sidecar: ${SIDE_CONT} state=${side_state} restarts=${side_restarts} NetworkMode=${side_netmode}"

echo "--- Sidecar logs (last 20) ---"
docker logs "$SIDE_CONT" --tail 20 2>&1 || true

bind_out="$(docker exec "$APP_CONT" ss -tlnp 2>/dev/null || docker exec "$APP_CONT" netstat -tlnp 2>/dev/null || true)"
if echo "$bind_out" | grep -q ':8888 '; then
  APP_PORT=8888
fi
echo "--- App bind :${APP_PORT} ---"
echo "$bind_out" | grep ":${APP_PORT} " || echo "(nothing on :${APP_PORT})"

app_curl="$(docker exec "$APP_CONT" curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://127.0.0.1:${APP_PORT}/" 2>/dev/null || echo 000)"
echo "App self-curl: HTTP ${app_curl}"

sidecar_curl_local="000"
serve_status=""
sidecar_curl_app_ip="000"
app_ip=""
best_backend=""

if [ "$side_state" = "running" ]; then
  sidecar_curl_local="$(docker exec "$SIDE_CONT" curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://127.0.0.1:${APP_PORT}/" 2>/dev/null || echo 000)"
  echo "Sidecar curl localhost:${APP_PORT}: HTTP ${sidecar_curl_local}"

  app_ip="$(docker inspect "$APP_CONT" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}' 2>/dev/null | awk '{print $1}')"
  if [ -n "$app_ip" ]; then
    sidecar_curl_app_ip="$(docker exec "$SIDE_CONT" curl -s -o /dev/null -w '%{http_code}' --connect-timeout 3 "http://${app_ip}:${APP_PORT}/" 2>/dev/null || echo 000)"
    echo "Sidecar curl ${app_ip}:${APP_PORT}: HTTP ${sidecar_curl_app_ip}"
  fi

  serve_status="$(docker exec "$SIDE_CONT" tailscale serve status 2>&1 || true)"
  echo "--- tailscale serve status ---"
  echo "$serve_status"
fi

if [[ "$app_netmode" == container:* ]]; then
  best_backend="http://127.0.0.1:${APP_PORT}"
  layout="shared_netns"
elif [ "$sidecar_curl_local" != "000" ]; then
  best_backend="http://127.0.0.1:${APP_PORT}"
  layout="localhost_ok"
elif [ "$sidecar_curl_app_ip" != "000" ] && [ -n "$app_ip" ]; then
  best_backend="http://${app_ip}:${APP_PORT}"
  layout="bridge_ip"
else
  best_backend=""
  layout="broken_netns"
fi

echo "--- Diagnosis ---"
if [ "$side_state" = "restarting" ] || [ "${side_restarts:-0}" -gt 2 ]; then
  echo "Sidecar unstable — fix crash cause before serve."
fi
if [ "$layout" = "broken_netns" ]; then
  echo "Sidecar cannot reach app — redeploy with openclaw network_mode: service:tailscale"
fi
if echo "$serve_status" | grep -q '127.0.0.1:8080'; then
  echo "WARN: serve may target :8080 (Tailscale listener). OpenClaw nginx uses :8888."
fi

if [ "$APPLY_FIX" = true ]; then
  echo "--- Apply fix ---"
  if [ "$side_state" != "running" ]; then
    echo "SKIP: sidecar not running"
  elif [ -z "$best_backend" ]; then
    echo "SKIP: no reachable backend"
  else
    echo "Applying: tailscale serve --bg --https=443 ${best_backend}"
    docker exec "$SIDE_CONT" tailscale serve --bg --https=443 "$best_backend"
    docker exec "$SIDE_CONT" tailscale serve status || true
    ext_code="$(curl -sk -o /dev/null -w '%{http_code}' --connect-timeout 10 https://openclaw.tiger-bushmaster.ts.net/ 2>/dev/null || echo 000)"
    echo "External curl after fix: HTTP ${ext_code}"
  fi
else
  echo "Run with --apply-fix to reapply tailscale serve when sidecar is running."
fi
