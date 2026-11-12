#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
need_local_playwright "Full Playwright suite blocked" || exit $?
cd "$ROOT/frontend" || exit 2
# The dedicated config starts the in-memory mock and Vite frontend. Do not start another mock manually.
port_status 5174 || { echo "STOP: frontend port is not free; identify the listener."; exit 2; }
port_status 8003 || { echo "STOP: mock port is not free; identify the listener."; exit 2; }
run_logged "All three Task 06 browser smoke tests (B-01, B-02, B-03)" ./node_modules/.bin/playwright test --config=playwright.task06-smoke.config.ts --reporter=list
