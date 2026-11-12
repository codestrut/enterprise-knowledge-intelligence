#!/bin/bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

API_CONTAINER="ekip-task07-api"
PORT="8004"
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$*"; }

docker inspect "$API_CONTAINER" >/dev/null 2>&1 || fail "API container does not exist."
running="$(docker inspect -f '{{.State.Running}}' "$API_CONTAINER")"
[[ "$running" == "true" ]] || { docker logs --tail 80 "$API_CONTAINER"; fail "API container is not running."; }

printf '===== WAIT FOR API HEALTH =====\n'
healthy=0
for _ in $(seq 1 90); do
  status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$API_CONTAINER")"
  [[ "$status" == "healthy" ]] && { healthy=1; break; }
  [[ "$status" == "unhealthy" ]] && break
  sleep 2
done
[[ "$healthy" -eq 1 ]] || { docker logs --tail 100 "$API_CONTAINER"; fail "Docker health check did not become healthy (status: $status)."; }
pass "Docker health check is healthy."

for endpoint in health docs openapi.json; do
  code="$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:${PORT}/${endpoint}")"
  [[ "$code" == "200" ]] || fail "/$endpoint returned HTTP $code."
  printf 'PASS: /%s HTTP %s\n' "$endpoint" "$code"
done

identity="$(docker exec "$API_CONTAINER" id)"
printf 'Runtime identity: %s\n' "$identity"
printf '%s' "$identity" | grep -q 'uid=10001' || fail "API is not running as UID 10001."
pass "Non-root runtime identity verified."

printf '\n===== VERIFY NETWORK AND PORT MAPPING =====\n'
docker port "$API_CONTAINER" | grep -q "127.0.0.1:${PORT}" || fail "Expected loopback-only port mapping not found."
docker inspect -f '{{range $name, $v := .NetworkSettings.Networks}}{{$name}} {{end}}' "$API_CONTAINER" | grep -qw ekip-task07-net || fail "API is not attached to the Task 07 network."
pass "Network attachment and loopback-only port mapping verified."

printf '\n===== VERIFY MODEL CACHE MOUNT =====\n'
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/models"}}RW={{.RW}} Type={{.Type}}{{end}}{{end}}' "$API_CONTAINER" | grep -q 'RW=false' || fail "Model cache mount is not read-only."
pass "Model cache is mounted read-only."

printf '\n===== MIGRATION HEAD =====\n'
docker exec "$API_CONTAINER" alembic current
printf '\n===== ENVIRONMENT VARIABLE PRESENCE (VALUES REDACTED) =====\n'
docker exec "$API_CONTAINER" python - <<'PY'
import os
required = ("EKIP_DATABASE_URL", "EKIP_ACCESS_TOKEN_SECRET", "EKIP_TENANT_DATA_DIRECTORY", "EKIP_ENABLE_API_DOCS", "HF_HOME", "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")
missing = [name for name in required if not os.environ.get(name)]
if missing:
    raise SystemExit("Missing required variables: " + ", ".join(missing))
print("PASS: required environment variables are present; values were not displayed.")
print("OPENAI_API_KEY present:", bool(os.environ.get("OPENAI_API_KEY")))
PY
pass "Task 07 deployment verification completed."
