#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
cd "$ROOT/frontend" || exit 2
failed=0
for task in "npm test" "npm run check" "npm run build"; do
  echo "OPTIONAL_CHECK=$task"
  case "$task" in
    "npm test") run_logged "Optional frontend unit tests" npm test || failed=1;;
    "npm run check") run_logged "Optional TypeScript check" npm run check || failed=1;;
    "npm run build") run_logged "Optional local production build" npm run build || failed=1;;
  esac
done
exit "$failed"
