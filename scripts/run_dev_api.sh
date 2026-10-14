#!/usr/bin/env bash
set -euo pipefail

# Keep Uvicorn reload scoped to source code. Editing tests, benchmark JSON,
# reports, docs, or generated artifacts won't restart the application and
# reload large transformer models unnecessarily.
exec uvicorn src.api.main:app --reload --reload-dir src
