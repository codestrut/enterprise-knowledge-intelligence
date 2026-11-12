#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
need_file "$ROOT/summarize_task06_pytests.py" || exit $?
run_logged "Pytest inventory" python3 "$ROOT/summarize_task06_pytests.py" --root "$ROOT"
