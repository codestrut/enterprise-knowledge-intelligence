#!/usr/bin/env bash
# Run EKIP PostgreSQL auth integration tests in a uniquely named disposable DB.
#
# Safety contract:
# - Uses only the existing, explicitly named local EKIP PostgreSQL test container.
# - Never connects tests to the container's default/shared database.
# - Creates one unique database and tags it with a per-run ownership marker.
# - Drops only that exact database, and only if its marker still matches.
# - Never removes/stops/recreates containers, volumes, images, or other databases.

set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
EXPECTED_CONTAINER="ekip-task05-postgres-test"
CONTAINER="${EKIP_TEST_POSTGRES_CONTAINER:-$EXPECTED_CONTAINER}"
HOST_PORT="55432"
DISPOSABLE_PREFIX="ekip_pg_run_test_"

if [[ "$CONTAINER" != "$EXPECTED_CONTAINER" ]]; then
  echo "ERROR: This runner is restricted to '$EXPECTED_CONTAINER'." >&2
  exit 2
fi

if [[ -n "${EKIP_TEST_DATABASE_URL:-}" ]]; then
  echo "ERROR: EKIP_TEST_DATABASE_URL is set." >&2
  echo "This disposable runner refuses externally supplied database URLs." >&2
  echo "Unset it and rerun to use a database created and owned by this runner." >&2
  exit 2
fi

if [[ "${EKIP_ALLOW_DISPOSABLE_PG_DB:-}" != "1" ]]; then
  echo "Refusing to create a disposable PostgreSQL database without explicit opt-in." >&2
  echo "After reviewing this script, run with:" >&2
  echo "  EKIP_ALLOW_DISPOSABLE_PG_DB=1 ./scripts/test_postgres_integration.sh" >&2
  exit 2
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
  echo "Set PYTHON_BIN or create the project's .venv first." >&2
  exit 2
fi

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is unavailable." >&2
  exit 2
fi

RUNNING="$(docker inspect --format '{{.State.Running}}' "$CONTAINER" 2>/dev/null || true)"
if [[ "$RUNNING" != "true" ]]; then
  echo "ERROR: Expected PostgreSQL container '$CONTAINER' is not running." >&2
  exit 2
fi

IMAGE="$(docker inspect --format '{{.Config.Image}}' "$CONTAINER")"
if [[ "$IMAGE" != "postgres:16-alpine" ]]; then
  echo "ERROR: Unexpected image for '$CONTAINER': $IMAGE" >&2
  echo "Expected exactly postgres:16-alpine; no resources were changed." >&2
  exit 2
fi

# Verify the only published PostgreSQL endpoint is the expected loopback port.
docker inspect "$CONTAINER" | "$PYTHON_BIN" -c '
import json, sys
items = json.load(sys.stdin)
ports = items[0].get("NetworkSettings", {}).get("Ports") or {}
bindings = ports.get("5432/tcp") or []
if not any(b.get("HostIp") == "127.0.0.1" and b.get("HostPort") == "55432" for b in bindings):
    raise SystemExit("ERROR: expected 127.0.0.1:55432 -> container 5432 binding was not found.")
'


# Verify the protected PostgreSQL data volume before accessing credentials.
docker inspect "$CONTAINER" | "$PYTHON_BIN" -c '
import json, sys

container = json.load(sys.stdin)[0]
mounts = container.get("Mounts", [])

valid = any(
    m.get("Type") == "volume"
    and m.get("Name") == "ekip_task05_pgdata"
    and m.get("Destination") == "/var/lib/postgresql/data"
    for m in mounts
)

if not valid:
    raise SystemExit(
        "ERROR: expected protected PostgreSQL volume was not verified."
    )
'

CONTAINER_ENV="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER")"
DB_USER="$(printf '%s\n' "$CONTAINER_ENV" | sed -n 's/^POSTGRES_USER=//p' | head -n 1)"
DB_PASSWORD="$(printf '%s\n' "$CONTAINER_ENV" | sed -n 's/^POSTGRES_PASSWORD=//p' | head -n 1)"
unset CONTAINER_ENV

DB_USER="${DB_USER:-ekip_test}"
if [[ -z "$DB_PASSWORD" ]]; then
  echo "ERROR: POSTGRES_PASSWORD is not configured in '$CONTAINER'." >&2
  exit 2
fi

# The role is used as an SQL identifier below; accept only simple PostgreSQL role names.
if [[ ! "$DB_USER" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
  echo "ERROR: PostgreSQL role name contains unsupported characters; refusing to continue." >&2
  exit 2
fi

RUN_TOKEN="$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(12))')"
DISPOSABLE_DB="${DISPOSABLE_PREFIX}$(date +%Y%m%d%H%M%S)_$$_${RUN_TOKEN:0:8}"
OWNERSHIP_MARKER="ekip-disposable:${RUN_TOKEN}"
CREATED_DB=0
CLEANUP_FAILED=0

psql_admin() {
  # Send the password over stdin, not in Docker's process arguments.
  docker exec -i "$CONTAINER" sh -c '
    IFS= read -r PGPASSWORD || exit 1
    export PGPASSWORD
    user="$1"
    shift
    exec psql -X -v ON_ERROR_STOP=1 -U "$user" -d postgres "$@"
  ' sh "$DB_USER" "$@" <<< "$DB_PASSWORD"
}

cleanup() {
  local original_status=$?
  set +e

  if [[ "$CREATED_DB" -eq 1 ]]; then
    echo "Cleaning up disposable PostgreSQL database: $DISPOSABLE_DB"

    local observed_marker
    observed_marker="$(psql_admin -Atq -c \
      "SELECT COALESCE(shobj_description(oid, 'pg_database'), '') FROM pg_database WHERE datname = '$DISPOSABLE_DB';" \
      2>/dev/null)"
    local marker_status=$?

    if [[ "$marker_status" -ne 0 || "$observed_marker" != "$OWNERSHIP_MARKER" ]]; then
      echo "ERROR: Cleanup refused: database ownership marker did not match." >&2
      echo "The database was NOT dropped. Inspect it manually; no other resource was touched." >&2
      CLEANUP_FAILED=1
    else
      psql_admin -c \
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DISPOSABLE_DB' AND pid <> pg_backend_pid();" \
        >/dev/null
      local terminate_status=$?

      if [[ "$terminate_status" -ne 0 ]]; then
        echo "ERROR: Could not close connections to the exact disposable database." >&2
        CLEANUP_FAILED=1
      else
        psql_admin -c "DROP DATABASE \"$DISPOSABLE_DB\";" >/dev/null
        local drop_status=$?
        if [[ "$drop_status" -ne 0 ]]; then
          echo "ERROR: Failed to drop disposable database '$DISPOSABLE_DB'." >&2
          CLEANUP_FAILED=1
        else
          echo "Disposable database cleanup confirmed."
        fi
      fi
    fi
  fi

  unset DB_PASSWORD EKIP_TEST_DATABASE_URL
  if [[ "$CLEANUP_FAILED" -ne 0 && "$original_status" -eq 0 ]]; then
    exit 90
  fi
  exit "$original_status"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Creating isolated PostgreSQL database: $DISPOSABLE_DB"
psql_admin -c "CREATE DATABASE \"$DISPOSABLE_DB\" OWNER \"$DB_USER\";"
CREATED_DB=1

psql_admin -c \
  "COMMENT ON DATABASE \"$DISPOSABLE_DB\" IS '$OWNERSHIP_MARKER';" \
  >/dev/null

export EKIP_TEST_DATABASE_URL="$(EKIP_RUN_DB_USER="$DB_USER" EKIP_RUN_DB_PASSWORD="$DB_PASSWORD" EKIP_RUN_DB_NAME="$DISPOSABLE_DB" "$PYTHON_BIN" -c '
import os
from urllib.parse import quote
user = quote(os.environ["EKIP_RUN_DB_USER"], safe="")
password = quote(os.environ["EKIP_RUN_DB_PASSWORD"], safe="")
database = quote(os.environ["EKIP_RUN_DB_NAME"], safe="")
print(f"postgresql+psycopg://{user}:{password}@127.0.0.1:55432/{database}")
')"

# Keep the credential out of the subprocess environment used to construct the URL.
unset EKIP_RUN_DB_USER EKIP_RUN_DB_PASSWORD EKIP_RUN_DB_NAME

if [[ "$#" -eq 0 ]]; then
  set -- tests/integration/test_auth_postgres.py
fi

echo "Running PostgreSQL integration tests against the isolated database."
echo "Test target: $*"
set +e
"$PYTHON_BIN" -m pytest -q "$@"
TEST_EXIT=$?
set -e

exit "$TEST_EXIT"
