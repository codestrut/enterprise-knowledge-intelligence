# EKIP UI Verification Report

**Date:** 2026-10-16  
**Branch:** `feature/organisation-knowledge-management`  
**HEAD:** `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`  
**Scope:** Diagnose and safely restore the current UI, then verify its current Task 04/05 login, library, and knowledge workspace. Task 06 implementation was not started.

## Outcome

The UI rendered successfully at `http://127.0.0.1:5173/`, but two Vite servers competed for port 5173. The IPv6 listener had no API target configured, and the existing Vite fallback sent API requests to production port 8000. The IPv4 listener was already configured for the isolated test API at port 8001. A clean browser session therefore could select the unsafe/misconfigured listener; a first-load 401 also incorrectly displayed an expired-session notice.

The focused fix changes Vite's fallback to `127.0.0.1:8001` and rejects non-loopback/non-8001 proxy targets before startup. It also suppresses the expired-session message when no authenticated profile existed. No request was sent to port 8000. After the fix, config loading confirmed the default is port 8001 and rejects a configured port 8000 target. Vite dev server startup is part of Playwright's browser run and uses strict loopback binding at `127.0.0.1:4173`.

## Evidence and screen results

The complete screen-by-screen matrix is in [UI_VERIFICATION_MATRIX.md](UI_VERIFICATION_MATRIX.md). The live Playwright run used `ekip-api-test` on `127.0.0.1:8001`, `ekip-task05-postgres-test` on `127.0.0.1:55432`, a fresh synthetic contributor and a runtime-only synthetic PDF. The PDF was uploaded, queried and deleted through the UI; the API returned `file_deleted=true` and `cleanup_required=false`. The synthetic identity/organisation and attributed audit rows remain in the isolated auth database. No existing documents or volumes were removed.

The run verified invalid login (401), login/profile, dashboard, keyboard navigation, empty library, upload/list, a grounded answer with a source-number-consistent citation and grounding passage, insufficient-evidence refusal, loading/error/retry UI, delete confirmation keyboard dismissal, deletion, logout and revoked-token rejection. Viewport checks covered the 390-pixel login screen and desktop app without horizontal overflow. The browser saw 3 expected HTTP-status console messages (401 and simulated 503); there were 0 uncaught page errors and 0 failed network requests. No browser request escaped the frontend proxy origin. The 503 was injected by the browser test; it was not a live API outage.

The initial investigation also found port 5173 already occupied by two Vite listeners. The browser interaction with the old competing listener was avoided after identifying that its fallback targeted production. The configuration fix and proxy-target guard were validated directly; no production request was used to validate them.

## Changes

Files changed for this UI diagnosis/verification:

- `frontend/vite.config.ts` — isolated API fallback and strict loopback/8001 target validation; retained the existing Vitest include configuration.
- `frontend/src/AuthContext.tsx` — show expiration only when a previously authenticated profile existed.
- `frontend/src/App.test.tsx` — regression coverage for clean unauthenticated entry versus an expired authenticated session.
- `frontend/e2e/smoke.spec.ts` — make reduced-motion screenshot assertion work when the browser has no `currentSrc`.
- `frontend/e2e/workspace-flow.spec.ts` — live browser workflow with synthetic PDF generation in memory and explicit response/citation/deletion checks.

The repository already had a large uncommitted Task 04/05 implementation. Those files and reports remain as found. The aggregate diff is not attributable solely to this UI check; see [UI_VERIFICATION_CHANGE_INVENTORY.md](UI_VERIFICATION_CHANGE_INVENTORY.md). No `data/` contents were opened, modified, or included in the archive.

## Verification commands and results

All frontend commands ran from `frontend/` unless stated otherwise:

| Command | Result |
|---|---|
| `npm run check` | PASS, `tsc --noEmit`, exit 0. |
| `npm test -- --reporter=dot` | PASS, 4 files and 90 tests passed, exit 0. |
| `npm run build` | PASS, TypeScript check and Vite production build; 38 modules transformed, exit 0. |
| `npm run test:e2e` with in-process `EKIP_API_PROXY_TARGET=http://127.0.0.1:8001` and synthetic `EKIP_E2E_LOGIN_*` variables | PASS, 3 Playwright tests passed in 9.8s. No credentials were printed. Browser console: 3 expected HTTP-status messages; 0 uncaught page errors; 0 failed network requests. Playwright emitted a `NO_COLOR`/`FORCE_COLOR` warning from Node/Vite. |
| `git diff --check` from repository root | PASS, exit 0. |
| Vite `loadConfigFromFile` with proxy target unset | PASS: effective target was `http://127.0.0.1:8001`. |
| Vite `loadConfigFromFile` configured with `http://127.0.0.1:8000` | PASS: configuration rejected the production target before server startup. No HTTP request was made to port 8000. |

The Playwright E2E command was run through a wrapper that created a fresh synthetic contributor in the isolated auth database, passed credentials only to the child test process, redacted them from captured output, and used a runtime-only PDF. The UI's scoped delete response confirmed removal. Audit attribution records were intentionally retained. Docker inspection confirmed the isolated test API and PostgreSQL ports; production container was only identified by `docker ps` and not contacted or changed.

## Limitations and status

- An actually expired access token was not waited out or manually simulated in the browser. A revoked token was checked live and returned 401; initial unauthenticated entry and expired-session messaging have regression coverage.
- The mobile viewport assertion covered login; the authenticated workflow was verified at desktop width. Narrow-screen layout of every authenticated screen is **NOT TESTED**.
- Browser/API behavior was checked against the current isolated test service, not production. No production requests, restarts, rebuilds, migrations, or volume operations occurred.
- The browser injected a synthetic 503 to verify loading/error/retry states; no real server outage was induced.
- Model behavior was verified with one synthetic grounded fact and one absent fact, not a broad quality benchmark.
- Node/Vite reported a `NO_COLOR`/`FORCE_COLOR` warning. It did not affect verification.

**UI restoration decision: PASS for the tested isolated MVP paths, with the limitations above.** Task 06 remains paused and not implemented. Production release remains unverified.

## Git snapshot and continuation

Branch and HEAD are listed above. The current working tree remains dirty with pre-existing Task 04/05 changes, this UI work, and unrelated untracked paths including `data/` (not inspected or packaged). No staged changes were made by this work; no commit, push, reset, clean, stash, branch switch, or production operation was performed. A complete path-only status snapshot and tracked diff are in the review archive. Tracked diff stat at this snapshot: 22 files changed, 1,970 insertions and 1,081 deletions; this includes preserved Task 04/05 work. `git diff --check` passed.

Continue by reviewing this report and the versioned archive first. Preserve all existing changes. Do not begin Task 06 until separately requested; if requested, begin with design and acceptance criteria review under `docs/engineering/IMPLEMENTATION_HANDOFF_STANDARD.md`. Keep test API activity on `127.0.0.1:8001` and production port 8000 / `ekip_data` untouched.
