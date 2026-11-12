#!/bin/bash
# EKIP Task 06: automated plan/content audit + technical verification.
# Run from any directory on the Mac. Does not reset Git, delete files, kill processes,
# run migrations, or call production APIs. Creates a timestamped audit folder under the repo.
set -uo pipefail

ROOT="/Users/joseph/enterprise-knowledge-intelligence"
FRONTEND="$ROOT/frontend"
STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT="$ROOT/docs/task-06/audit-run-$STAMP"

if [[ ! -d "$ROOT/.git" || ! -d "$FRONTEND" ]]; then
  echo "ERROR: Expected EKIP repository/frontend not found at:"
  echo "  $ROOT"
  exit 2
fi

mkdir -p "$OUT" || exit 2
LOG="$OUT/execution.log"
REPORT="$OUT/audit-report.md"
exec > >(tee -a "$LOG") 2>&1

overall_fail=0
run_step() {
  local label="$1"; shift
  echo
  echo "===== $label ====="
  "$@"
  local rc=$?
  echo "EXIT_CODE[$label]=$rc"
  if [[ $rc -ne 0 ]]; then overall_fail=1; fi
  return 0
}
port_check() {
  local phase="$1"
  echo
  echo "===== PORT CHECK: $phase ====="
  local occupied=0
  for port in 5174 8003; do
    echo "--- PORT $port ---"
    if lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null; then
      echo "PORT_STATUS[$port]=OCCUPIED"
      occupied=1
    else
      echo "No listening process found"
      echo "PORT_STATUS[$port]=FREE"
    fi
  done
  return "$occupied"
}

echo "EKIP TASK 06 AUTOMATED AUDIT AND VERIFICATION"
echo "Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Repository: $ROOT"
echo "Output folder: $OUT"
echo "Safety: no destructive Git commands, process killing, migrations, or production API calls."

echo
echo "===== REPOSITORY BASELINE ====="
cd "$ROOT" || exit 2
pwd
git branch --show-current
git status --short
BASELINE_RC=$?
echo "EXIT_CODE[repository baseline]=$BASELINE_RC"
[[ $BASELINE_RC -eq 0 ]] || overall_fail=1

port_check "before tests"
PREPORT_RC=$?
if [[ $PREPORT_RC -ne 0 ]]; then
  echo "BLOCKED: One or more test ports are occupied. No test suite will be started."
  echo "Identify the listener(s) manually. This script will not kill processes."
  overall_fail=1
else
  cd "$FRONTEND" || exit 2
  run_step "Playwright version" npx playwright --version
  run_step "Installed browsers" npx playwright install --list
  run_step "List smoke tests" npx playwright test --config=playwright.task06-smoke.config.ts --list

  # Static plan audit runs even if a prerequisite command failed.
  echo
  echo "===== AUTOMATED TEST-PLAN / DOCUMENTATION AUDIT ====="
  python3 - "$ROOT" "$OUT" <<'PY'
import re, sys
from pathlib import Path

root = Path(sys.argv[1])
out = Path(sys.argv[2])
checklist = root / "docs" / "task-06" / "EKIP_Task06_Test_Implementation_Checklist.md"
if not checklist.exists():
    # Look in the repo first, then the usual macOS Downloads location for the generated checklist.
    candidates = list(root.rglob("*Test*Implementation*Checklist*.md"))
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        candidates.extend(downloads.glob("*Test*Implementation*Checklist*.md"))
    checklist = candidates[0] if candidates else checklist

spec_candidates = [
    root / "frontend" / "e2e" / "task06-platform.smoke.spec.ts",
    root / "frontend" / "e2e" / "task06-platform.smoke.spec.js",
]
spec = next((p for p in spec_candidates if p.exists()), None)
config = root / "frontend" / "playwright.task06-smoke.config.ts"
task_docs = root / "docs" / "task-06"

findings = []
def result(status, item, detail):
    findings.append((status, item, detail))
    print(f"{status}: {item} — {detail}")

if checklist.exists():
    md = checklist.read_text(encoding="utf-8", errors="replace")
    result("PASS", "Checklist exists", str(checklist.relative_to(root)))
    for label, pattern in [
        ("scenario section", r"Expected browser scenarios"),
        ("acceptance criteria mention", r"acceptance criteria"),
        ("scope limitation", r"synthetic, in-memory mock API"),
        ("pre/post port checks", r"5174.*8003|8003.*5174"),
        ("test commands", r"npm test.*npm run check.*npm run build|npm test"),
    ]:
        result("PASS" if re.search(pattern, md, re.I | re.S) else "REVIEW REQUIRED",
               label, "found in checklist" if re.search(pattern, md, re.I | re.S) else "not explicitly found")
else:
    result("REVIEW REQUIRED", "Checklist file", "could not find the Markdown checklist inside the repository; provide/copy it into the project to audit its contents")

if spec:
    ts = spec.read_text(encoding="utf-8", errors="replace")
    result("PASS", "Playwright spec exists", str(spec.relative_to(root)))
    titles = re.findall(r"\btest\s*\(\s*['\"`]([^'\"`]+)", ts)
    expected = [
        ("tenant directory / lifecycle states", r"tenant directory|lifecycle states"),
        ("registration / user search / role assignment", r"pending registration|search a user|assign a role"),
        ("approval / recovery / retry", r"approve|recover|retry"),
    ]
    for label, pat in expected:
        found = bool(re.search(pat, ts, re.I))
        result("PASS" if found else "REVIEW REQUIRED", label,
               "matching wording found in spec" if found else "expected workflow wording not found")
    if len(titles) >= 3:
        result("PASS", "Test declarations", f"{len(titles)} test title(s) found")
    else:
        result("REVIEW REQUIRED", "Test declarations", f"found {len(titles)} title(s); expected three or more")
else:
    result("REVIEW REQUIRED", "Playwright spec", "expected smoke spec file not found")

result("PASS" if config.exists() else "REVIEW REQUIRED",
       "Playwright configuration",
       "task06-smoke config exists" if config.exists() else "task06-smoke config missing")

if task_docs.exists():
    files = [p for p in task_docs.rglob("*") if p.is_file()]
    result("PASS" if files else "REVIEW REQUIRED", "Task 06 source documents",
           f"{len(files)} file(s) found under docs/task-06")
    pdfs = [p for p in files if p.suffix.lower() == ".pdf"]
    result("REVIEW REQUIRED", "Requirements traceability",
           f"{len(pdfs)} PDF(s) present; this script does not extract/semantically verify every PDF requirement. Manual/source-aware traceability review remains necessary.")
else:
    result("REVIEW REQUIRED", "Task 06 source documents", "docs/task-06 directory not found")

result("REVIEW REQUIRED", "Semantic requirement coverage",
       "static checks confirm workflow keywords, not that every Task 06 requirement is satisfied; a human must map each authoritative requirement to a test and acceptance criterion")

with (out / "plan-audit-findings.txt").open("w", encoding="utf-8") as f:
    for status, item, detail in findings:
        f.write(f"{status}\t{item}\t{detail}\n")
print(f"PLAN_AUDIT_FINDINGS={len(findings)}")
PY
  PLAN_RC=$?
  echo "EXIT_CODE[test-plan audit]=$PLAN_RC"
  [[ $PLAN_RC -eq 0 ]] || overall_fail=1

  run_step "Playwright smoke suite" npx playwright test --config=playwright.task06-smoke.config.ts
  run_step "Frontend unit tests" npm test
  run_step "TypeScript check" npm run check
  run_step "Production build (local only)" npm run build
fi

echo
echo "===== POST-RUN STATE ====="
cd "$ROOT" || exit 2
port_check "after tests"
POSTPORT_RC=$?
if [[ $POSTPORT_RC -ne 0 ]]; then
  echo "REVIEW REQUIRED: one or more test ports remain occupied; inspect manually."
  overall_fail=1
fi
echo "--- Git status after run ---"
git status --short
GIT_RC=$?
echo "EXIT_CODE[final git status]=$GIT_RC"
[[ $GIT_RC -eq 0 ]] || overall_fail=1

cat > "$REPORT" <<EOF
# EKIP Task 06 — Automated Audit and Verification

- Started: $(date '+%Y-%m-%d %H:%M:%S %Z')
- Repository: \`$ROOT\`
- Branch at run start: see \`execution.log\`
- Detailed command output: \`execution.log\`
- Static test-plan findings: \`plan-audit-findings.txt\`

## Interpretation

This run checks the local Playwright prerequisites and suite, frontend tests, TypeScript, build, ports, Git status, and selected checklist/spec content. It does **not** prove that every requirement in Task 06 source PDFs is covered. The plan audit intentionally leaves semantic requirement traceability as **REVIEW REQUIRED** until each authoritative requirement is mapped to a test and an observable acceptance criterion.

The smoke suite uses a synthetic in-memory mock API; passing results do not establish database persistence, live production API behaviour, or production readiness.

## Exit status

Overall technical command status: $([[ $overall_fail -eq 0 ]] && echo "no command failure detected" || echo "one or more checks failed or were blocked"). Review the complete execution log and static findings before treating the run as complete.
EOF

echo
echo "===== FINISHED ====="
echo "Report: $REPORT"
echo "Log: $LOG"
echo "Plan findings: $OUT/plan-audit-findings.txt"
if [[ $overall_fail -ne 0 ]]; then
  echo "OVERALL_STATUS=CHECK_FAILURE_OR_BLOCKED"
  exit 1
else
  echo "OVERALL_STATUS=TECHNICAL_COMMANDS_COMPLETED_REVIEW_FINDINGS"
  exit 0
fi
