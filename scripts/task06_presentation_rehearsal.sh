#!/usr/bin/env bash
# EKIP Task 06 — guided presentation rehearsal
# macOS / zsh or bash compatible. This script does not reset Git, delete files,
# kill processes, run migrations, start Docker, or call the production API.

set -u

REPO="/Users/joseph/enterprise-knowledge-intelligence"
FRONTEND="$REPO/frontend"
CONFIG="playwright.task06-smoke.config.ts"

pause() {
  printf '\n%s\n' "$1"
  read -r -p "Press Return to continue, or Ctrl+C to stop... " _
}

check_port() {
  local port="$1"
  echo "===== PORT $port ====="
  if ! command -v lsof >/dev/null 2>&1; then
    echo "ERROR: lsof is not available; cannot safely check port $port."
    return 2
  fi
  local listeners
  listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$listeners" ]]; then
    printf '%s\n' "$listeners"
    echo "ERROR: Port $port is occupied. No process was stopped. Resolve this manually, then rerun."
    return 1
  fi
  echo "No listening process found"
}

printf '%s\n' '============================================================'
printf '%s\n' 'EKIP Task 06 — Guided Presentation Rehearsal'
printf '%s\n' '============================================================'
printf '%s\n' 'Safety: no Git cleanup/reset, file deletion, process killing, database migration, Docker, or production API calls.'

if [[ ! -d "$REPO/.git" ]]; then
  echo "ERROR: Repository not found at: $REPO"
  echo "Edit REPO at the top of this script if your project is elsewhere."
  exit 1
fi
if [[ ! -d "$FRONTEND" ]]; then
  echo "ERROR: Frontend directory not found: $FRONTEND"
  exit 1
fi

pause "STEP 1/7 — Confirm repository, branch, and existing changes"
cd "$REPO" || exit 1
echo "===== PROJECT LOCATION ====="
pwd
echo "===== CURRENT GIT BRANCH ====="
git branch --show-current
echo "===== EXISTING CHANGES ====="
git status --short

pause "STEP 2/7 — Confirm isolated test ports are free (5174 frontend, 8003 mock API)"
check_port 5174 || exit 1
check_port 8003 || exit 1

pause "STEP 3/7 — Check Playwright version and installed browsers"
cd "$FRONTEND" || exit 1
echo "===== PLAYWRIGHT VERSION ====="
npx playwright --version || exit 1
echo "===== INSTALLED PLAYWRIGHT BROWSERS ====="
npx playwright install --list || exit 1

pause "STEP 4/7 — Confirm the expected smoke tests are discoverable"
npx playwright test --config="$CONFIG" --list || exit 1

pause "STEP 5/7 — Run the isolated browser smoke suite"
echo "This starts the configured isolated frontend/mock API. Do not interrupt unless it hangs or errors."
npx playwright test --config="$CONFIG"
TEST_EXIT=$?
if [[ "$TEST_EXIT" -ne 0 ]]; then
  echo "\nSMOKE SUITE FAILED (exit code $TEST_EXIT). Review the output before continuing."
else
  echo "\nSMOKE SUITE PASSED. Review the summary above (expected: 3 passed)."
fi

pause "STEP 6/7 — Check that temporary test ports are no longer listening"
cd "$REPO" || exit 1
PORT_CHECK_EXIT=0
check_port 5174 || PORT_CHECK_EXIT=1
check_port 8003 || PORT_CHECK_EXIT=1
if [[ "$PORT_CHECK_EXIT" -ne 0 ]]; then
  echo "One or more ports remain occupied. No process was stopped; inspect the owning process manually."
fi

pause "STEP 7/7 — Review Git status after the run (no cleanup is performed)"
echo "===== POST-RUN GIT STATUS ====="
git status --short

echo "\n===== REHEARSAL SUMMARY ====="
if [[ "$TEST_EXIT" -eq 0 && "$PORT_CHECK_EXIT" -eq 0 ]]; then
  echo "PASS: smoke suite completed successfully and both test ports are free."
else
  echo "CHECK NEEDED: smoke exit code=$TEST_EXIT; port check exit code=$PORT_CHECK_EXIT. Review the output above."
fi

echo "\nOptional broader frontend checks (run separately if they are part of your presentation):"
echo "  cd \"$FRONTEND\""
echo "  npm test"
echo "  npm run check"
echo "  npm run build"
echo "These commands are intentionally not run automatically by this script."

if [[ "$TEST_EXIT" -ne 0 ]]; then exit "$TEST_EXIT"; fi
if [[ "$PORT_CHECK_EXIT" -ne 0 ]]; then exit 2; fi
exit 0
