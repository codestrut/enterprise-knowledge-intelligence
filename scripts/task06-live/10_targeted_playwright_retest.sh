#!/bin/bash
# Run only the named browser test after a failure; title must be copied from --list output.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
if [[ $# -lt 1 ]]; then
  echo 'Usage: bash scripts/task06-live/10_targeted_playwright_retest.sh "<exact Playwright test title>"' | tee -a "$RUN_LOG"
  exit 2
fi
need_local_playwright "Targeted Playwright retest blocked" || exit $?
cd "$ROOT/frontend" || exit 2
port_status 5174 || { echo "STOP: frontend port 5174 is not free; identify the listener."; exit 2; }
port_status 8003 || { echo "STOP: mock port 8003 is not free; identify the listener."; exit 2; }
run_logged "Targeted Playwright retest" ./node_modules/.bin/playwright test --config=playwright.task06-smoke.config.ts --grep "$1" --reporter=list
