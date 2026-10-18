# UI Verification Change Inventory

## Changes for this verification

- `frontend/vite.config.ts` (tracked, modified): default API proxy now targets isolated loopback port 8001; non-HTTP, non-loopback, non-8001 targets are rejected. Existing `test.include` setting was retained.
- `frontend/src/AuthContext.tsx` (untracked in this repository snapshot): initial unauthenticated 401 no longer produces an expired-session alert; a previously authenticated profile still does.
- `frontend/src/App.test.tsx` (tracked, modified): regression assertions for clean login and authenticated session expiration. This file also contains earlier Task 04/05 tests in the same aggregate diff.
- `frontend/e2e/smoke.spec.ts` (untracked): current live proxy/auth smoke tests, including reduced-motion source assertion resilient to empty `currentSrc`.
- `frontend/e2e/workspace-flow.spec.ts` (untracked): real browser workflow, runtime-generated PDF, live grounded/refusal queries, citation consistency, error/loading/retry state, deletion and session revocation.

## Existing changes preserved

The working tree contained extensive Task 04 and Task 05 source, tests, configuration, documentation and untracked files before and during this UI review. The complete `git status --short` snapshot is in `git-status.txt` in the archive. The reported aggregate tracked diff is 22 files, 1,970 insertions and 1,081 deletions; it includes earlier task work and must not be treated as the change size of this UI verification alone. The staged diff was empty at the last inspection.

No files in `data/` were inspected, read, modified, staged, or packaged. Existing Task 04 `HANDOFF_REPORT.md` and Task 05 `HANDOFF_REPORT_TASK05.md` were read as context and were not overwritten. No backend source, Docker configuration, API container, database schema, or production resource was changed for this UI verification.

The archive's `git-diff.patch` is a safe tracked patch restricted to `frontend/vite.config.ts` and `frontend/src/App.test.tsx`; untracked frontend source is included separately under `frontend/` and identified above. The complete repository diff is not a UI-only diff because it contains preserved prior task changes.
