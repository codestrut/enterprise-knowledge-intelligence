#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
cd "$ROOT" || exit 2
run_logged "Post-run Git status" git status --short
for port in 5174 8003; do port_status "$port" || true; done
printf 'POST_RUN_EVIDENCE_DIR=%s\n' "$RUN_DIR" | tee -a "$RUN_LOG"
