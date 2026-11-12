#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
need_file "$ROOT/EKIP_Task06_Environment_Check.sh" || exit $?
run_logged "Read-only Task 06 environment preflight" bash "$ROOT/EKIP_Task06_Environment_Check.sh"
