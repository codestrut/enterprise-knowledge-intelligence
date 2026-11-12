#!/bin/bash
# Generate live-summary.md from terminal.log and environment-report.txt.
# The generator invocation itself is appended to terminal.log after the summary is built.
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; . "$HERE/lib.sh"
need_file "$HERE/summarize_live_run.py" || exit $?
start="$(now_utc)"; start_s="$(date '+%s')"
cmd="python3 $HERE/summarize_live_run.py --run-dir $RUN_DIR"
output="$(python3 "$HERE/summarize_live_run.py" --run-dir "$RUN_DIR" 2>&1)"
rc=$?
end="$(now_utc)"; elapsed=$(($(date '+%s')-start_s))
{
  printf '\n===== Generate terminal-derived live summary =====\nSTART=%s\nCOMMAND=%s\n' "$start" "$cmd"
  printf '%s\n' "$output"
  printf 'END=%s\nDURATION_SECONDS=%s\nEXIT_CODE=%s\n' "$end" "$elapsed" "$rc"
} | tee -a "$RUN_LOG"
exit "$rc"
