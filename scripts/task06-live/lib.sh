#!/bin/bash
# Shared command logger for EKIP Task 06 live exercise. macOS Bash 3.2 compatible.
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${TASK_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
STAMP="${TASK06_RUN_STAMP:-$(date '+%Y%m%d-%H%M%S')}"
RUN_DIR="${TASK06_RUN_DIR:-$ROOT/docs/task-06/live-runs/$STAMP}"
mkdir -p "$RUN_DIR" || { echo "Cannot create evidence folder: $RUN_DIR"; exit 2; }
RUN_LOG="${TASK06_RUN_LOG:-$RUN_DIR/terminal.log}"
now_utc() { date -u '+%Y-%m-%dT%H:%M:%SZ'; }
run_logged() {
  local label="$1"; shift
  local start end start_s end_s elapsed rc
  start="$(now_utc)"; start_s="$(date '+%s')"
  {
    printf '\n===== %s =====\n' "$label"
    printf 'START=%s\nCOMMAND=' "$start"
    printf '%q ' "$@"
    printf '\n'
  } | tee -a "$RUN_LOG"
  "$@" 2>&1 | tee -a "$RUN_LOG"
  rc=${PIPESTATUS[0]}
  end="$(now_utc)"; end_s="$(date '+%s')"; elapsed=$((end_s-start_s))
  printf 'END=%s\nDURATION_SECONDS=%s\nEXIT_CODE=%s\n' "$end" "$elapsed" "$rc" | tee -a "$RUN_LOG"
  return "$rc"
}
need_file() {
  if [[ ! -f "$1" ]]; then
    printf 'BLOCKED: required file missing: %s\n' "$1" | tee -a "$RUN_LOG"
    return 2
  fi
}
log_blocked() {
  local label="$1"; local reason="$2"; local stamp
  stamp="$(now_utc)"
  {
    printf '\n===== %s =====\nSTART=%s\nCOMMAND=prerequisite check\n' "$label" "$stamp"
    printf 'BLOCKED: %s\n' "$reason"
    printf 'END=%s\nDURATION_SECONDS=0\nEXIT_CODE=2\n' "$(now_utc)"
  } | tee -a "$RUN_LOG"
}
need_local_playwright() {
  local label="${1:-Playwright prerequisite}"
  if [[ ! -x "$ROOT/frontend/node_modules/.bin/playwright" ]]; then
    log_blocked "$label" "project-local CLI missing at frontend/node_modules/.bin/playwright"
    return 2
  fi
}
port_status() {
  local port listeners
  port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    printf 'PORT_%s=UNKNOWN (lsof unavailable)\n' "$port" | tee -a "$RUN_LOG"
    return 2
  fi
  listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "$listeners" ]]; then
    printf 'PORT_%s=BUSY\n%s\n' "$port" "$listeners" | tee -a "$RUN_LOG"
    return 1
  fi
  printf 'PORT_%s=FREE\n' "$port" | tee -a "$RUN_LOG"
  return 0
}
printf 'RUN_DIR=%s\nRUN_LOG=%s\n' "$RUN_DIR" "$RUN_LOG" | tee -a "$RUN_LOG"
