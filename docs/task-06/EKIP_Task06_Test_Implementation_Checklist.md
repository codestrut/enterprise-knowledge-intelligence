# EKIP Task 06 — Test Implementation Checklist

**Purpose:** Track the Task 06 test-design, isolated browser smoke-test, frontend verification, and post-run review workflow.

**Scope:** The browser smoke suite uses a synthetic, in-memory mock API. Passing results validate the scripted browser workflows; they do not establish database persistence, live production API behaviour, or production readiness.

**Repository:** `/Users/joseph/enterprise-knowledge-intelligence`\
**Branch observed during rehearsal:** `feature/organisation-knowledge-management`\
**Frontend directory:** `frontend`

---

## Status key

- [ ] Not started
- [x] Completed and verified
- [ ] Blocked — record the reason in the execution notes

Only mark an item complete after checking the actual command output. If a check fails, preserve the output and investigate before proceeding.

## 1. Define the test approach

- [ ] Review the Task 06 scope and identify the behaviours that must be validated.
- [ ] Define the test scenarios and expected behaviour for each scenario.
- [ ] Define pass/fail acceptance criteria.
- [ ] Identify test dependencies and any scope limitations.
- [ ] Record the agreed test plan before execution.

## 2. Inspect the repository and test environment

Run from macOS Terminal:

```bash
cd /Users/joseph/enterprise-knowledge-intelligence || exit 1
pwd
git branch --show-current
git status --short
```

- [ ] Confirm the repository path and active branch.
- [ ] Review existing modifications and untracked files.
- [ ] Preserve existing project work; do not run destructive Git cleanup/reset commands.

Check the isolated test ports:

```bash
for port in 5174 8003; do
  echo "===== PORT $port ====="
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || echo "No listening process found"
done
```

- [ ] Confirm port `5174` is free before starting the smoke suite.
- [ ] Confirm port `8003` is free before starting the smoke suite.
- [ ] If a port is occupied, identify the process and investigate; do not kill it automatically.

## 3. Verify browser test prerequisites

Run from the frontend directory:

```bash
cd /Users/joseph/enterprise-knowledge-intelligence/frontend || exit 1
npx playwright --version
npx playwright install --list
npx playwright test --config=playwright.task06-smoke.config.ts --list
```

- [ ] Confirm Playwright responds with its installed version.
- [ ] Confirm the required browser is installed.
- [ ] Confirm all expected Task 06 tests are discovered.

Expected browser scenarios:

- [ ] Tenant directory displays synthetic lifecycle states through the loopback proxy.
- [ ] Platform operator can create a pending registration, search for a user, and assign a role.
- [ ] Platform operator can approve, recover, and retry without activating tenants.

## 4. Execute the isolated browser smoke suite

From `frontend`:

```bash
npx playwright test --config=playwright.task06-smoke.config.ts
```

- [ ] Run the suite and capture the actual output.
- [ ] Confirm the test count and pass/fail summary.
- [ ] If any test fails, preserve the complete failure output and investigate before continuing.
- [ ] Do not delete test results or change tests merely to obtain a passing result.

**Previously observed result:** 3 browser tests passed in 4.1 seconds. This is historical evidence from the earlier rehearsal; rerun and record the current result for a new execution.

## 5. Run broader frontend verification

Run each command separately from `frontend`.

### Frontend tests

```bash
npm test
```

- [ ] Review the complete test summary.
- [ ] Record test files passed/failed, tests passed/failed, and duration.

**Previously observed result:** 6 test files passed; 123 tests passed in 2.70 seconds.

### TypeScript check

```bash
npm run check
```

- [ ] Confirm the command finishes without TypeScript errors.
- [ ] Record any errors or warnings.

**Previously observed result:** `tsc --noEmit` completed without reported errors.

### Production build

```bash
npm run build
```

- [ ] Confirm the build succeeds.
- [ ] Record the build output and duration.
- [ ] Treat this as a local build, not a deployment.

**Previously observed result:** Vite 7.3.7 transformed 39 modules and completed the build in 611 ms.

## 6. Verify post-execution state

Check the test ports again:

```bash
cd /Users/joseph/enterprise-knowledge-intelligence || exit 1

for port in 5174 8003; do
  echo "===== PORT $port ====="
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || echo "No listening process found"
done
```

Review Git status:

```bash
git status --short
```

- [ ] Confirm ports `5174` and `8003` are free.
- [ ] Review Git status and identify any new or updated test artifacts.
- [ ] Preserve existing project changes and untracked files.
- [ ] Do not assume that a clean Git status is expected.

**Previously observed result:** the guided rehearsal script reported both test ports free after the smoke suite. Final manual port checks also showed both ports free.

## 7. Document the outcome

- [ ] Record the date/time and environment used for the run.
- [ ] Record exact commands executed and their actual results.
- [ ] Document failures, warnings, fixes, and retest outcomes.
- [ ] Link or reference relevant test outputs and defect notes.
- [ ] Keep planned work separate from completed and verified work.
- [ ] Update the Derived Commands & Rehearsal Guide and Presentation Runbook if the verified workflow changes.

## Final summary template

Fill this in only after the current execution has completed.

| Check | Result | Evidence / notes |
|---|---|---|
| Test approach defined | Pending | |
| Preflight and ports | Pending | |
| Playwright/browser prerequisites | Pending | |
| Browser smoke suite | Pending | |
| Frontend test suite | Pending | |
| TypeScript check | Pending | |
| Production build | Pending | |
| Post-run ports | Pending | |
| Git status reviewed | Pending | |

## Limitations and safety notes

- The isolated browser suite uses a synthetic, in-memory mock API.
- Passing browser tests do not prove database persistence, live production API behaviour, or production readiness.
- Do not run production migrations or use production services as part of this isolated smoke-test checklist.
- Do not use `git reset`, `git clean`, destructive deletion, or automatic process killing to prepare the environment.
