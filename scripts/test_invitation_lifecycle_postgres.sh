#!/usr/bin/env bash
# Verify migration 0008 round-trip and invitation lifecycle/concurrency in a fresh,
# disposable local PostgreSQL database. The database is dropped on exit.
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 2

CONTAINER="${EKIP_TEST_POSTGRES_CONTAINER:-ekip-task05-postgres-test}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
RUN_STAMP="$(date +%Y%m%d_%H%M%S)"
TEST_DB_NAME="ekip_invitation_lifecycle_test_${RUN_STAMP}_$$"
LOG="${HOME}/Desktop/EKIP_Invitation_Lifecycle_${RUN_STAMP}.log"
DB_CREATED=false

finish() {
    local status=$?
    trap - EXIT
    if [[ "$DB_CREATED" == "true" ]]; then
        echo "--- CLEAN UP DISPOSABLE DATABASE ---"
        if docker exec "$CONTAINER" sh -lc \
            'dropdb -U "$POSTGRES_USER" --if-exists "$1"' sh "$TEST_DB_NAME"; then
            echo "Removed disposable database: $TEST_DB_NAME"
        else
            echo "ERROR: Could not remove disposable database: $TEST_DB_NAME" >&2
            [[ $status -ne 0 ]] || status=1
        fi
    fi
    echo "Test log preserved at: $LOG"
    exit "$status"
}
trap finish EXIT

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python executable not found: $PYTHON_BIN" >&2
    exit 2
fi
if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
    echo "ERROR: PostgreSQL test container not found: $CONTAINER" >&2
    exit 2
fi
RUNNING="$(docker inspect --format '{{.State.Running}}' "$CONTAINER")"
if [[ "$RUNNING" != "true" ]]; then
    echo "ERROR: PostgreSQL test container is not running." >&2
    exit 2
fi

DB_EXISTS="$(docker exec "$CONTAINER" sh -lc \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT datname FROM pg_database"' \
    | grep -Fx "$TEST_DB_NAME" || true)"
if [[ -n "$DB_EXISTS" ]]; then
    echo "ERROR: Generated database name already exists; refusing to reuse it." >&2
    exit 2
fi

echo "Creating isolated database: $TEST_DB_NAME"
if ! docker exec "$CONTAINER" sh -lc \
    'createdb -U "$POSTGRES_USER" "$1"' sh "$TEST_DB_NAME"; then
    echo "ERROR: Could not create isolated PostgreSQL database." >&2
    exit 2
fi
DB_CREATED=true

CONTAINER_ENV="$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$CONTAINER")"
DB_USER="$(printf '%s\n' "$CONTAINER_ENV" | sed -n 's/^POSTGRES_USER=//p' | head -n 1)"
DB_PASSWORD="$(printf '%s\n' "$CONTAINER_ENV" | sed -n 's/^POSTGRES_PASSWORD=//p' | head -n 1)"
DB_USER="${DB_USER:-ekip_test}"
if [[ -z "$DB_PASSWORD" ]]; then
    unset CONTAINER_ENV
    echo "ERROR: PostgreSQL password not found in the test container environment." >&2
    exit 2
fi

export EKIP_TEST_DATABASE_URL="$(DB_USER="$DB_USER" DB_NAME="$TEST_DB_NAME" DB_PASSWORD="$DB_PASSWORD" \
    "$PYTHON_BIN" -c 'import os; from urllib.parse import quote_plus; print("postgresql+psycopg://" + quote_plus(os.environ["DB_USER"]) + ":" + quote_plus(os.environ["DB_PASSWORD"]) + "@127.0.0.1:55432/" + quote_plus(os.environ["DB_NAME"]))')"
unset DB_PASSWORD CONTAINER_ENV

if ! "$PYTHON_BIN" - <<'PY'
import os
from sqlalchemy.engine import make_url
url = make_url(os.environ.get("EKIP_TEST_DATABASE_URL", ""))
assert url.drivername == "postgresql+psycopg", "Unexpected PostgreSQL driver"
assert url.host == "127.0.0.1", "Test database must be on loopback"
assert url.database and "test" in url.database.lower(), "Database name must contain test"
print(f"Verified disposable target: {url.host}/{url.database}")
PY
then
    exit 2
fi

echo "Checking migration 0008 upgrade -> downgrade -> re-upgrade on an empty database..."
if ! EKIP_DATABASE_URL="$EKIP_TEST_DATABASE_URL" "$PYTHON_BIN" -m alembic upgrade head; then
    exit 1
fi
if ! EKIP_DATABASE_URL="$EKIP_TEST_DATABASE_URL" "$PYTHON_BIN" -m alembic downgrade 0007_tenant_admin; then
    exit 1
fi
if ! EKIP_DATABASE_URL="$EKIP_TEST_DATABASE_URL" "$PYTHON_BIN" -m alembic upgrade head; then
    exit 1
fi

echo "Running populated-0007 to 0008 migration regression..."
if ! "$PYTHON_BIN" -m pytest -q \
    tests/integration/test_invitation_lifecycle_migration_postgres.py 2>&1 | tee -a "$LOG"; then
    exit 1
fi

echo "Running PostgreSQL invitation lifecycle and route-concurrency regressions..."
echo "Log: $LOG"
if "$PYTHON_BIN" -m pytest -q \
    tests/integration/test_invitation_lifecycle_postgres.py \
    tests/integration/test_invitation_concurrency_postgres.py 2>&1 | tee -a "$LOG"; then
    STATUS=0
else
    STATUS=$?
fi
exit "$STATUS"
