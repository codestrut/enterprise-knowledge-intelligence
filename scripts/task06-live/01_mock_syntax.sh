#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
need_file "$ROOT/scripts/task06_smoke_mock_api.py" || exit $?
run_logged "Python mock API syntax" python3 -m py_compile "$ROOT/scripts/task06_smoke_mock_api.py"
