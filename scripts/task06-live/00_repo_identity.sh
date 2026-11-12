#!/bin/bash
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
cd "$ROOT" || exit 2
run_logged "Repository identity and initial Git state" bash -c 'pwd; git rev-parse --show-toplevel; git branch --show-current; git rev-parse --short HEAD; git status --short'
