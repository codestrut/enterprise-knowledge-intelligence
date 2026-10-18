# EKIP Task 05 — Run A (audit fixes) handoff report

**Run ID:** `runa-20261017T020841` · **Date:** 2026-10-17 · **Branch:** `feature/organisation-knowledge-management` · **HEAD:** `eeb3a1b7a4112acfa0bc09f8d872cac5a071b0c9` (unchanged)

**Authorisation:** Run A under Option C. The test container `ekip-api-test` and its volumes were not touched, and live-container and Playwright checks are NOT VERIFIED. No staging, commit, tag, push, reset, clean, stash, rebase or branch switch was performed. Gate A has not started.

**Binding-document limitation:** `docs/security/EKIP_Task_05_Implementation_Proposal_v2.md` does not exist and the owner cannot provide it. **Compliance with that proposal is NOT VERIFIED.** All acceptance below is judged only against `AGENTS.md`, the implementation handoff standard, `docs/task05_identity_database.md`, `HANDOFF_REPORT_TASK05.md` and the master run prompt.

## 1. Executive summary

- **Delivered:** all 15 Run A items, test-first. Backend: B1–B7 and P1–P4. Frontend: F1–F4, with F3 using the documented fallback.
- **Backend suite:** **296 → 331 passed**, 0 failed, 1 skipped, 15 deselected. Sandboxed and offline, with the approved protected-data exclusions.
- **PostgreSQL integration:** **6 passed**.
- **Vitest:** **90 (historical) → 101 passed**, stable across 6 consecutive runs.
- **Frontend tooling:** `npm run check` and `npm run build` pass.
- **NOT VERIFIED:** the live test-container rebuild and Playwright runs (Option C). The e2e specs compile under `playwright test --list`, and an owner procedure is in `docs/task05_run_a_live_verification.md`.
- **Recommendation:** Run A is code-complete and verified at unit, API, PostgreSQL, frontend and build level. Close it after owner review **and** after the live and browser checks are completed in an isolated environment.

## 2. Architecture and implementation (by item)

| Item | Change | Files |
|---|---|---|
| **B1** login and refresh throttling | New `FailureThrottle` (details below the table); 429 with `Retry-After` and fixed text; Argon2 concurrency semaphore. | `src/auth/throttling.py` (new), `src/auth/passwords.py`, `src/api/main.py` |
| **B2** filenames after restore | Restore updates the live in-memory record and chunk metadata via a shared `set_original_filename`, not the copy returned by `add_pdf`. | `src/api/tenant_storage.py`, `src/api/main.py` |
| **B3** no internal exception text | Unexpected upload, query and delete errors return a 5xx with fixed text plus a `request_id` (body and `X-Request-ID`), logging only the exception type. Deliberate PDF-content `ValueError`s return a fixed-text 400. Pipeline `ValueError`s (e.g. a missing LLM key) are internal and now return 500 instead of 400 with the raw message. | `src/api/main.py` |
| **B4** signing key at startup | `validate_signing_key_configuration()` runs in the app lifespan before tenant restore. Startup fails with `Startup refused: EKIP_ACCESS_TOKEN_SECRET must contain at least 32 bytes.` The key value is never echoed. | `src/auth/access_tokens.py`, `src/api/main.py` |
| **B5** safe bootstrap | `bootstrap_organisation(..., allow_existing_org=False)` (CLI `--allow-existing-org`). Without the override, an existing organisation is refused, even before the password prompt. A name mismatch is refused. An addition is audited as `organisation.bootstrap_admin_added` with `existing_organisation: true`. An idempotent re-run for an existing admin still returns `already_configured`. | `src/auth/bootstrap.py` |
| **B6** input length limits | Question at most **4,000** characters; password at most **128** code points (the existing policy cap, plus the 512-byte service bound); upload filename at most **255** (422 with fixed text). 422 responses no longer echo values for `password`, `refresh_token` or `rotation_key`; other 422s are unchanged. | `src/api/main.py` |
| **B7** database outage | Database errors during token revalidation return **503** "Authentication service is temporarily unavailable." instead of a generic 500. Access remains denied. | `src/auth/dependencies.py` |
| **P1** no request content in logs | Every `[RAG DEBUG]` line, including question text, is gated behind `EKIP_DEBUG_RETRIEVAL_LOGGING` (default off). The diagnostic-only hybrid probe runs only in debug mode, since its result was only ever logged. Retrieval and grounding failures log the exception type only unless debugging. | `src/rag_pipeline.py` |
| **P2** API docs off by default | `/docs`, `/redoc` and `/openapi.json` exist only when `EKIP_ENABLE_API_DOCS` is true. | `src/api/main.py` |
| **P3** safe download headers | `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff`. | `src/api/main.py` |
| **P4** token claims match the database | Test-only. A validly signed token with a mismatched organisation, membership, user or family is rejected with 401. The existing checks already enforced this, so no code change was needed. | `tests/api/test_api_acceptance.py` |
| **F1** clear session state | The API client keeps a session-generation counter, so responses from an earlier session are discarded and never refresh or retry. The knowledge-base context is driven by auth status: sign-out, expiry or unknown clears it, and late results are dropped. Workspace aborts its in-flight query on unmount. | `frontend/src/api/client.ts`, `KnowledgeBaseContext.tsx`, `Workspace.tsx` |
| **F2** explicit auth states | `unknown` → `signedIn` / `signedOut` (details below the table). Permissions fail closed (`null` = deny). | `AuthContext.tsx`, `App.tsx`, `DocumentLibrary.tsx`, `styles.css` |
| **F3** multi-organisation sign-in (**fallback**) | `signIn` returns `signedIn`, `needsOrganisation` or `noOrganisation`. The password is kept until real success. Choices reset when the email changes. An empty choice list shows fixed text. | `AuthContext.tsx`, `LoginPage.tsx`, `styles.css`, `e2e/smoke.spec.ts` |
| **F4** fixed login error text | Fixed messages for 401, 429, 422, 5xx, network failure and anything else; raw server text is never rendered. | `LoginPage.tsx` |

**B1 detail.**
- **Pair backoff:** per normalised account and direct client address. The first 5 failures are free; after that each failure blocks the pair for 1, 2, 4, … seconds, capped at 15 minutes.
- **Per-address cap:** looser, at 50 failures per 15 minutes.
- **Storage:** counters expire after 15 minutes idle and are bounded at 10,000 entries.
- **Refresh:** counts only rejected tokens (10 free), so valid same-key retries never count.
- **Argon2 cap:** `EKIP_ARGON2_MAX_CONCURRENCY`, default 4, allowed range 1–16; invalid values stop startup.
- **Single worker only:** counters reset on restart and aren't shared across workers.

**F2 detail.**
- One StrictMode-safe `GET /api/auth/me` resolves the initial state.
- **200:** signed in. **401:** signed out with no message. **Network error or 5xx:** signed out, with the fixed text "We couldn't confirm your sign-in status. Sign in to continue."
- While the state is `unknown`, the page shows a neutral "Checking your session…" status, and no app shell or controls render.

**F3 fallback, and why.** A signed, single-use selection ticket needs new server-side state and a new endpoint, which is more than the master prompt's "small endpoint change", so the documented fallback was used. The single-use ticket remains a follow-up.

**Migrations and compatibility.**
- **No database migrations.**
- **No new dependencies:** throttling uses the standard library only.
- **API contract changes:**
  - 429 is a new status on `/auth/login` and `/auth/refresh`;
  - unexpected 5xx bodies gain a `request_id` field;
  - query pipeline configuration faults move from 400 to 500;
  - oversized inputs return 422;
  - API docs are disabled unless explicitly enabled.
- **Deployment compatibility (B4):** any environment running this code, including a future production rebuild, **must** set `EKIP_ACCESS_TOKEN_SECRET` (at least 32 bytes) or the service will refuse to start. The running production container was not touched or inspected beyond a port listing.

## 3. Changed-file inventory

This run changed 25 existing or new files and added 3 documentation files. All other uncommitted work (Task 04, 05.1, 05.2, login and reports) is preserved unchanged. The tree was compared against start-state copies taken at the beginning of the run. Several files were already uncommitted Task 04/05 work, so their HEAD-relative diffs mix tasks; the run-relative patches in the archive isolate this run.

- **Backend source:** `src/api/main.py` (tracked), `src/rag_pipeline.py` (tracked), `src/api/tenant_storage.py`, `src/auth/access_tokens.py`, `src/auth/bootstrap.py`, `src/auth/dependencies.py`, `src/auth/passwords.py`, `src/auth/throttling.py` (**new**).
- **Backend tests:** `tests/api/test_api_acceptance.py` (tracked; 12 new tests and an extended restore test), `tests/unit/test_auth_bootstrap.py` (4 new), `tests/unit/test_auth_throttling.py` (**new**, 17), `tests/unit/test_rag_pipeline_logging.py` (**new**, 2).
- **Frontend source:** `frontend/src/api/client.ts`, `App.tsx`, `Workspace.tsx`, `styles.css` (all tracked), `AuthContext.tsx`, `KnowledgeBaseContext.tsx`, `DocumentLibrary.tsx`, `LoginPage.tsx`.
- **Frontend tests:**
  - `AuthSession.test.tsx` (**new**, 11) and `test-fixtures/auth.ts` (**new**).
  - `App.test.tsx` (tracked) and `DocumentLibrary.test.tsx`: fixture updates only, listed in section 5.
  - `e2e/smoke.spec.ts`: F2 page-load updates and a new guarded multi-organisation test.
- **Docs:** `docs/task05_run_a_live_verification.md` (**new**), this report (**new**), and a Run A section appended to `HANDOFF_REPORT_TASK05.md`. `HANDOFF_REPORT.md` was not edited.

## 4. Security and safety assessment

- **New trust boundaries or routes:** none; there are no new endpoints.
- **Abuse resistance (B1):** brute force and the Argon2 memory and CPU flood are now bounded in-process.
  - **Assumption:** the API sees the real client address.
  - **Risk:** behind a reverse proxy, every client shares the proxy address, so the per-address cap and the pair backoff would be shared across users. Trusted forwarded-address handling is out of scope and is a deployment prerequisite for meaningful per-client throttling.
  - **Limits:** counters are per-process and reset on restart.
- **Information hygiene:**
  - B3: no exception text or paths in responses; logs record only exception types and request IDs.
  - B6: credential values are not echoed in 422 responses.
  - P1: default logs contain no questions, answers, prompts, retrieved text or filenames. Tests assert canaries are absent from captured logs.
  - P2: interactive docs are off by default.
  - P3: downloads can't be MIME-sniffed or displayed inline.
- **Tenant and session isolation:**
  - P4 confirms a forged-but-signed token can't cross membership, user, organisation or session.
  - F1 removes cross-user leakage of document metadata and answers in a shared browser.
  - F2 keeps protected UI from rendering before auth resolves and makes permissions fail closed.
- **Operator safety (B5):** bootstrap can no longer silently grant admin on an existing tenant.
- **Not tested:** live browser behaviour and real reverse-proxy deployment.
- **Test resources:**
  - Backend and frontend tools ran under a macOS sandbox that blocks any read or write inside `data/`, `.env` contents and non-local network (profile `verification/pytest-sandbox.sb`), with zero sandbox denials.
  - `PYTHON_DOTENV_DISABLED=1` stopped the code loading `.env`; models stayed offline (local cache only).
  - The tenant root pointed at a scratch directory.
  - PostgreSQL ran only on the isolated `ekip-task05-postgres-test` (loopback 55432, database name contains `test`). Its URL was built in-process and never printed.
- **Protected resources:**
  - **Production:** `ekip-api` received no HTTP requests; only a read-only `docker port` and `lsof` listing. `ekip_data` was not touched.
  - **`ekip-api-test`:** not stopped, rebuilt or modified (created and started 2026-10-16T15:36, still running). `ekip_task04_test_data` and `ekip_task04_test_hf_cache` were not accessed.
- **Secret scan:** pattern scan of all 25 run-changed files and the saved diffs found no credentials; literal matches are synthetic test values or variable names. gitleaks is not installed, so this was a pattern scan only.

## 5. Verification evidence

All commands ran from the repository root unless noted.

- **Backend runner:** `env -u EKIP_TEST_DATABASE_URL PYTHON_DOTENV_DISABLED=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 EKIP_TENANT_DATA_DIRECTORY=<scratch> PYTHONDONTWRITEBYTECODE=1 sandbox-exec -f verification/pytest-sandbox.sb .venv/bin/pytest -p no:cacheprovider …`.
- **Frontend runner:** from `frontend/`, `NO_COLOR=1 sandbox-exec -f verification/pytest-sandbox.sb …`.

| Check (type) | Command | Result |
|---|---|---|
| Backend baseline (unit + API) | `… pytest -rs $(cat verification/pytest-exclusions.txt)`, Gate 0 | **296 passed, 1 skipped, 15 deselected, 0 failed** |
| Backend final (unit + API) | same | **331 passed, 1 skipped, 15 deselected, 0 failed** (+35 new tests); 1 torch deprecation warning; 0 sandbox denials |
| PostgreSQL integration | `tests/integration/test_auth_postgres.py` via an in-process URL wrapper (`verification/run_pg_integration.py`) | **6 passed** (4.29 s) |
| Vitest (frontend unit) | `npx vitest run` | **101 passed** (5 files), 6 of 6 consecutive runs; the historical baseline was 90 |
| Type check | `npm run check` | PASS (`tsc --noEmit`) |
| Production build | `npm run build` | PASS (38 modules; git-ignored `dist/`) |
| E2E compile only | `npx playwright test --list` | 5 tests listed; nothing run, and no web server started (port 4173 stayed free) |
| Live container + Playwright | — | **NOT VERIFIED** (Option C); procedure in `docs/task05_run_a_live_verification.md` |
| Whitespace | `git diff --check`, plus a `--no-index --check` equivalent for untracked files | clean |
| Port 8000 (read-only) | `docker port ekip-api`; `lsof -iTCP:8000 -sTCP:LISTEN` | `0.0.0.0:8000` and `[::]:8000`: **listens on all interfaces, not loopback.** Flagged for the owner; not changed |

**Skipped and excluded:**
- **Skip:** the PostgreSQL integration module inside the backend runner, because `EKIP_TEST_DATABASE_URL` is unset there. It was run separately above.
- **Excluded:** 35 tests that read protected `data/` (approved exclusion list): `tests/evaluation/` (5), `test_document_independent_benchmark.py` (15, read at import), and 15 individually deselected tests (`verification/pytest-exclusions.txt`).

**Failing-first evidence** (`verification/evidence/`):
- **B1:** `src.auth.throttling` missing; the API had no `FailureThrottle`.
- **B2:** restore returned a UUID filename instead of `persist-a.pdf`.
- **B3:** 400 with raw text.
- **B4:** startup did not raise.
- **B5:** bootstrap did not raise; the CLI exited 0.
- **B6:** an over-long question returned 200.
- **B7:** an uncaught `OperationalError`.
- **P1:** the canary question was in the logs.
- **P2:** docs returned 200.
- **P3:** no `nosniff`.
- **F1–F4:** all 11 new Vitest tests failed for the expected reasons.
- **Passed before by design:** P4 (test-only), "docs can be enabled" and "debug logging appears with the flag".

**Test fixtures updated for the intended F2 behaviour change (no assertion removed or loosened).** F2 forbids rendering the app before auth resolves. 28 existing tests had rendered signed-in pages with mocks that ignored auth, and those 28 failed before the update (evidence log). Changes:
- New `test-fixtures/auth.ts` `withAuthenticatedProfile()` answers only `GET /api/auth/me`. Existing mocks never see that call, so all call-count assertions are unchanged. Applied to `mockApi()`, the two "offline" App tests (keeping their intent: signed in, with status endpoints failing) and all 14 fetch stubs in `DocumentLibrary.test.tsx`.
- App test 1's `/api/auth/me` mock now requires the bearer token, matching the real API and that test's own `/documents` mock.
- Two assertions that raced the now-asynchronous session check were wrapped in `findAllByText` / `waitFor`. Their content is identical.
- E2E: page-load waits now target the 401 from `/api/auth/me` instead of `/api/documents`. The proxy test adds a stronger check that no `/api/documents` request happens before sign-in. The single-organisation precondition is now commented.

**The 111 vs 112 historical count.** The historical 13-file command currently gives **120 passed** (before Run A). The extra tests are consistent with those files' modification times (2026-10-16 16:30–16:34, after the 111/112 runs). The exact per-test difference can't be recovered because the files were never committed. Use 120 (pre-Run A) and 331 (full suite) as the current baselines.

**`httpx2` / `httpcore2` provenance.**
- Both are pinned in HEAD's `requirements.txt`, not introduced by uncommitted work.
- `openai` requires `httpx2>=2.12.0,<3`, `starlette[full]` lists it as an extra, and `httpx2` requires `httpcore2==2.13.0`.
- Package metadata: BSD-3-Clause, author Tom Christie, homepage `github.com/pydantic/httpx2`.
- The publisher's authenticity wasn't independently verified (network checks were not used).

## 6. Acceptance matrix

| Item | Test(s) | Result | Notes |
|---|---|---|---|
| F1 | `AuthSession.test.tsx` (2) | PASS (unit) | Browser check NOT VERIFIED |
| F2 | `AuthSession.test.tsx` (4) | PASS (unit) | Browser check NOT VERIFIED |
| F3 (fallback) | `AuthSession.test.tsx` (3); e2e multi-organisation test added | PASS (unit) | Live e2e NOT VERIFIED; single-use ticket deferred |
| F4 | `AuthSession.test.tsx` (2) | PASS (unit) | — |
| B1 | `test_auth_throttling.py` (17), API tests (2) | PASS | Single-worker, in-process; proxy caveat in section 4 |
| B2 | `test_restoration_after_registry_rebuild…` (extended) | PASS | — |
| B3 | 2 API tests | PASS | — |
| B4 | `test_startup_refuses…` (2) | PASS | Deployment-compatibility change; live container check NOT VERIFIED |
| B5 | `test_auth_bootstrap.py` (4 new) | PASS | — |
| B6 | `test_oversized_inputs…` | PASS | Question limit 4,000 |
| B7 | `test_protected_routes_return_503…` | PASS | — |
| P1 | `test_rag_pipeline_logging.py` (2) | PASS | `docker logs` canary check NOT VERIFIED (no container) |
| P2 | 2 API tests | PASS | — |
| P3 | 1 API test | PASS | — |
| P4 | 1 API test | PASS | No code change was required |
| Test-container rebuild + Playwright | — | **NOT VERIFIED** | Option C |
| Compliance with the missing proposal v2 | — | **NOT VERIFIED** | Document unavailable |

## 7. Known limitations and blockers

- **Release blocker:** the live container and browser checks (Option C). Complete them using the procedure document.
- **Release blocker (deployment):** B4 requires `EKIP_ACCESS_TOKEN_SECRET` in every environment, so confirm it before any production rebuild.
- **Follow-up:**
  - **Behind a proxy:** throttling needs trusted client-address handling.
  - **Single worker:** in-process counters (documented).
  - **F3:** single-use selection ticket.
  - **Port 8000 exposure:** production listens on all interfaces; owner decision.
  - **Tooling:** no gitleaks or `pip-audit` installed.
  - **Config template:** no `.env.example`; the new settings are documented in the procedure doc.
- **Unchanged out-of-scope list:**
  - per-model locks replacing the evaluator-wide grounding lock, and organisation-row locking;
  - the refresh-replay deadlock;
  - the upload-before-auth buffering investigation;
  - quotas and per-organisation LLM budget;
  - lazy isolation of corrupt tenant manifests;
  - live two-tenant canary proof;
  - refresh-token cookie, CSRF and CSP (Task 05.4).

## 8. Gate decision

**Run A: implementation complete; automated, PostgreSQL and build verification PASS; live and browser verification NOT VERIFIED (Option C).** Not ready to close until the owner reviews it and the live checks are completed or explicitly waived. Gate A has not started.

## 9. Git snapshot

- **Branch and HEAD:** `feature/organisation-knowledge-management` @ `eeb3a1b` (unchanged during the run).
- **Staged:** none. Commits, tags and pushes: none.
- **Status:** 76 entries, excluding `data/`. That's the 70 at run start plus 6 new untracked files:
  - `frontend/src/AuthSession.test.tsx`
  - `frontend/src/test-fixtures/auth.ts`
  - `tests/unit/test_auth_throttling.py`
  - `tests/unit/test_rag_pipeline_logging.py`
  - `docs/task05_run_a_live_verification.md`
  - this report

  `src/auth/throttling.py` sits inside the already-untracked `src/auth/` folder, and `HANDOFF_REPORT_TASK05.md` was already untracked.
- **Full lists:** `git-status.txt` and `git-diff.patch` in the archive.

## 10. Continuation

1. Review this report and the archive.
2. Complete the live checks with `docs/task05_run_a_live_verification.md` in an isolated environment, and record the results in the Run A section of `HANDOFF_REPORT_TASK05.md`.
3. Decide on the port 8000 binding, the proxy deployment and the F3 ticket follow-up.
4. Only then authorise Gate A (Task 05.3 hardening). It must re-check Git state and preserve Run A changes.
