#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
need_local_playwright "Playwright discovery blocked" || exit $?
need_file "$ROOT/frontend/playwright.task06-smoke.config.ts" || exit $?
need_file "$ROOT/frontend/e2e/task06-platform.smoke.spec.ts" || exit $?
cd "$ROOT/frontend" || exit 2
run_logged "Playwright version" ./node_modules/.bin/playwright --version || exit $?
run_logged "Playwright browser inventory" ./node_modules/.bin/playwright install --list || exit $?
run_logged "Task 06 browser-smoke discovery" ./node_modules/.bin/playwright test --config=playwright.task06-smoke.config.ts --list
