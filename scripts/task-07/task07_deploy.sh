#!/bin/bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

NETWORK="ekip-task07-net"
PG_CONTAINER="ekip-task07-postgres"
API_CONTAINER="ekip-task07-api"
TENANT_VOLUME="ekip-task07-tenant-data"
IMAGE="ekip-api:task07"
ENV_FILE=".env.task07"
PORT="8004"
CACHE="${HOME}/.cache/huggingface"

fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS: %s\n' "$*"; }

[[ -f "$ENV_FILE" ]] || fail "Missing $ENV_FILE. Run task07_prepare.sh first."
docker info >/dev/null 2>&1 || fail "Docker Desktop is unavailable."
docker image inspect "$IMAGE" >/dev/null 2>&1 || fail "Missing image $IMAGE."
docker network inspect "$NETWORK" >/dev/null 2>&1 || fail "Create $NETWORK manually in Docker Desktop first."
docker volume inspect ekip-task07-postgres-data >/dev/null 2>&1 || fail "Create ekip-task07-postgres-data manually in Docker Desktop first."
docker inspect "$PG_CONTAINER" >/dev/null 2>&1 || fail "Create $PG_CONTAINER manually in Docker Desktop first."
docker inspect -f '{{range $name, $v := .NetworkSettings.Networks}}{{$name}} {{end}}' "$PG_CONTAINER" | grep -qw "$NETWORK" || fail "PostgreSQL container is not attached to $NETWORK."
docker inspect -f '{{.State.Running}}' "$PG_CONTAINER" | grep -qx true || fail "PostgreSQL container is not running."

printf '===== WAIT FOR POSTGRESQL =====\n'
ready=0
for _ in $(seq 1 30); do
  if docker exec "$PG_CONTAINER" pg_isready -U ekip_task07 -d ekip_task07 >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[[ "$ready" -eq 1 ]] || fail "PostgreSQL did not become ready. Inspect its Docker Desktop logs."
pass "PostgreSQL accepts connections."

if docker inspect "$API_CONTAINER" >/dev/null 2>&1; then
  fail "$API_CONTAINER already exists. Verify the existing deployment; do not replace it automatically."
fi
if /usr/sbin/lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  fail "Host port $PORT is occupied. No process was stopped."
fi

printf '\n===== RUN ALEMBIC MIGRATIONS =====\n'
docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" "$IMAGE" alembic upgrade head
docker run --rm --network "$NETWORK" --env-file "$ENV_FILE" "$IMAGE" alembic current
pass "Alembic migration command completed."

printf '\n===== BOOTSTRAP DEMONSTRATION ORGANISATION =====\n'
printf 'The bootstrap command securely prompts for the administrator password.\n'
docker run --rm -it --network "$NETWORK" --env-file "$ENV_FILE" "$IMAGE" \
  python -m src.auth.bootstrap organisation \
  --name "EKIP Task 07 Demonstration" \
  --slug "ekip-task07-demo" \
  --admin-email "admin@adjacentlab.com" \
  --confirm
pass "Organisation bootstrap command completed."

docker volume inspect "$TENANT_VOLUME" >/dev/null 2>&1 || docker volume create "$TENANT_VOLUME" >/dev/null
printf '\n===== START API CONTAINER =====\n'
docker run -d \
  --name "$API_CONTAINER" \
  --network "$NETWORK" \
  --network-alias task07-api \
  --publish "127.0.0.1:${PORT}:8000" \
  --env-file "$ENV_FILE" \
  --mount "type=volume,source=${TENANT_VOLUME},target=/app/data/tenants" \
  --mount "type=bind,source=${CACHE},target=/models,readonly" \
  "$IMAGE"
pass "API container started."
printf 'Swagger UI: http://127.0.0.1:%s/docs\n' "$PORT"
printf 'Health:     http://127.0.0.1:%s/health\n' "$PORT"
printf '\nRun task07_verify.sh after the API has completed model initialisation.\n'
