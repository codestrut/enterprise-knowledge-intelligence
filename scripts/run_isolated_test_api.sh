#!/usr/bin/env bash
set -Eeuo pipefail

# Start EKIP's local API for frontend testing on the dedicated test port.
# This isolates the listener from the production port; it does not provide
# separate database, document-storage, or model-cache isolation.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

exec uvicorn src.api.main:app \
  --host 127.0.0.1 \
  --port 8002 \
  --reload \
  --reload-dir src
