# EKIP Task 05.2 — Engineering Handoff and Final Evidence Review

**Snapshot date:** 2026-10-16  
**Branch:** `feature/organisation-knowledge-management`  
**Commit:** `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`  
**Working tree:** dirty; existing Task 04 and Task 05 changes remain uncommitted. No staged changes.

This consolidated report supersedes older sections of the prior Task 05 handoff where they conflict. In particular, older text said that `/auth/me` and audit routes were absent, migration `0003` was current, and live RAG/auth remained unverified. Current source and latest live verification show `/auth/me` and the scoped audit reader implemented, migration `0004_scoped_security_audit` current, and live login/profile/logout plus live grounded/refusal RAG checks completed on the isolated service.

## 1. Executive summary

Task 05.2 extends the managed identity and permission foundation with protected API access, organisation-scoped document and RAG workspaces, session lifecycle endpoints, operation auditing, and a frontend login/library/query experience.

The implementation is present in the current working tree. The current source provides login, refresh rotation, logout/revocation, `/auth/me`, permission enforcement, per-organisation document storage and retrieval, scoped audit events and an `audit:read` reader. The isolated PostgreSQL schema is at `0004_scoped_security_audit`. Earlier recorded backend, PostgreSQL, frontend, TypeScript, build, and Playwright suites passed. In the latest continuation, 72 focused API/RAG/storage regression tests passed, and a live synthetic RAG scenario passed on `127.0.0.1:8001`: grounded answer and consistent citation, insufficient-evidence refusal, cross-organisation isolation, scoped operation audit, and API-scoped deletion.

**Task 05.2 decision: PASS for its reviewed MVP acceptance scope; it can be closed after external review.** Live behavior is now evidenced in the isolated environment, including authentication and RAG. This is not a production deployment approval. Model benchmark evaluation, production deployment, cross-tab refresh coordination, and broader operational hardening remain outside or beyond the demonstrated MVP. Task 06 has not started.

## 2. Architecture and implementation

### Identity, sessions, and permissions

- `src/auth/models.py` defines `Organisation`, `User`, `OrganisationMembership`, refresh-session records, and `AuditEvent`; memberships carry role assignments and enforce identity/membership constraints.
- `src/auth/passwords.py` provides password policy, Argon2 hashing, and verification. Password values are represented as secret inputs and are not returned in profile responses.
- `src/auth/access_tokens.py` issues and validates short-lived HMAC-signed access tokens. `src/auth/service.py` handles credential verification, membership choice, session creation/rotation/revocation, and failed-login audit events. Refresh material is stored/compared as hashes; a refresh family is revoked at logout.
- `src/auth/dependencies.py:get_authenticated_context` verifies bearer claims against active user, membership, organisation, and live refresh-family state in PostgreSQL. It derives permissions from the stored membership role via the existing `src/auth/permissions.py` definitions. Client-supplied identity or organisation values do not establish authority.
- `src/api/main.py` registers `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `GET /auth/me`, and protected document/query routes. `/auth/me` returns email, organisation id/name, role, and effective permissions only. `GET /health` is minimal and public.
- `require_permission` enforces document, query, and audit permissions. The audit reader filters by the authenticated organisation. Platform administration does not grant tenant-document or tenant-audit access without an authorised active membership.

### Tenant storage, retrieval, and evidence

- `src/api/tenant_storage.py:TenantWorkspaceRegistry` lazily creates UUID-scoped workspaces under `EKIP_TENANT_DATA_DIRECTORY` (default `data/tenants`). Each gets a separate manifest, upload directory, KnowledgeBase, chunk collection, and retrieval index. Paths are canonicalized, confined to the tenant root, and tenant directories reject symlinks.
- `src/api/main.py` uses the validated authenticated context to select the workspace for list, upload, status, download, query, and delete. Legacy global `data/uploads` and `data/documents_manifest.json` are not imported or assigned to an organisation.
- `src/knowledge_base.py`, `src/rag_pipeline.py`, and `src/retrieval/reranked_retriever.py` integrate tenant KBs with shared model components and tenant-specific retrieval. Citation source metadata is sanitized to a safe basename rather than local filesystem paths.
- Query responses include answer, retrieved `sources`, ranked `source_map`, citations, invalid-citation diagnostics, grounding/evidence state, refusal state, and generation-repair diagnostics where applicable. The live citation verifier cross-checked citation source number, matching source-map entry, `sources[number - 1]`, and available source/page/chunk metadata.

### Audit and sensitive data handling

- Failed login attempts and authentication/session security events are persisted without raw passwords, tokens, or raw question/document content.
- Upload, query, and delete operations create scoped events with actor, organisation, action, target, timestamp, outcome, and minimal details. Query text and document content are not persisted in event details.
- `/audit/events` requires `audit:read`, is read-only, and scopes returned rows to the caller's organisation. Unauthorized roles receive 403; cross-tenant data is filtered.
- Audit persistence is fail-closed for protected operations: inability to persist a required audit event returns 503; database failures are rolled back and logs report exception type, not credential/content values. This avoids silently claiming audited completion when persistence failed.

### Frontend

- `frontend/src/AuthContext.tsx` manages access/refresh state in memory and coordinates refresh/retry within a tab. Tokens are not written to browser storage; page reload requires sign-in. Upload/delete are not replayed after an ambiguous 401.
- `frontend/src/LoginPage.tsx`, `AppShell.tsx`, `DocumentLibrary.tsx`, `KnowledgeBaseContext.tsx`, and `frontend/src/api/client.ts` implement sign-in, live profile identity, role/permission-aware library actions, query integration, session refresh and logout. `frontend/e2e/smoke.spec.ts` exercises the isolated browser login/profile/logout flow.
- The supplied login GIF and reduced-motion poster exist at `frontend/public/images/` and were loaded in Playwright. No frontend source changed during the latest live RAG continuation.

### Database migrations

The Alembic chain is `0001_identity_foundation` → `0002_auth_refresh_sessions` → `0003_auth_hardening` → `0004_scoped_security_audit`. `migrations/versions/0004_scoped_security_audit.py` adds scoped audit persistence. The isolated PostgreSQL service was read at revision `0004_scoped_security_audit` during latest preflight. No migration ran against production; the latest RAG continuation ran no migration at all.

## 3. Security assessment

| Control | Evidence type | Result and boundary |
|---|---|---|
| Missing/invalid credentials and permission denial | API regression tests; live Playwright for unauthenticated and authenticated routes | Tests exercise 401/403 paths. Live browser observed login, profile, protected list, logout, then revoked-token 401 on port 8001. |
| Organisation selection and membership enforcement | Code review and API/PostgreSQL tests | Active membership and organisation are revalidated server-side; caller identifiers are not authority. |
| Cross-tenant documents and retrieval | Live API test with two synthetic organisations | Other organisation saw zero documents; unique-fact query refused with no citations/sources; cross-tenant file lookup returned 404. |
| Upload validation and rollback | API tests and live synthetic upload | PDF-only/size/content and duplicate paths are tested; live upload indexed one synthetic PDF. API operation audit start/finalization failure is surfaced as 503. Filesystem rollback after exceptional upload is best-effort and logs error type. |
| RAG evidence and citations | Live API test | Grounded answer had sufficient evidence and one consistent citation/source mapping. Missing-fact query refused with insufficient evidence. No production data used. |
| Session refresh/revocation | Unit/integration tests and live Playwright | Rotation/revocation passed prior tests; live logout invalidated the session and protected request returned 401. Refresh coordination is per tab; cross-tab behavior remains unverified/not implemented. |
| Audit scope and confidentiality | API tests plus read-only live DB inspection | Events matched actor, tenant, action, outcome, timestamp; details excluded content. Organisation B had its own query event, correctly scoped; an initial test-harness aggregate incorrectly rejected that event, then a corrected predicate passed. |
| Audit access control | API tests and live browser | `audit:read` required; reader denial observed live as 403. Organisation filtering is enforced in the query. |
| Filesystem and legacy data | Source review and isolated tests | Tenant paths are UUID-scoped/confined; no legacy global documents were imported. No protected local `data/` content was opened in this continuation. |
| Production safety | Read-only service inspection and command logs | No HTTP request to port 8000, no production migration/container operation, and no `ekip_data` mutation. |

Remaining security risks are mostly operational: in-memory tokens require reauthentication after reload; refresh synchronization across tabs is not implemented; there is no demonstrated rate limiting or production rollout, backup/retention policy, or model-load capacity test. These are not evidence of an observed tenant-boundary defect, but should be addressed before production release according to deployment policy.

## 4. Test and verification evidence

Results below are separated by when and how they were obtained. Historical tests are not represented as newly run in the latest continuation.

### Latest continuation (2026-10-16)

| Command/action | Environment and purpose | Actual result |
|---|---|---|
| Read-only `docker ps --filter name=ekip-api-test --filter name=ekip-api --filter name=ekip-task05-postgres-test --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'` | Inspect test API, PostgreSQL, and production service boundaries | Test API loopback 8001, PostgreSQL loopback 55432, production API 8000. |
| Read-only `docker inspect --format '{{.Name}} image={{.Config.Image}} imageID={{.Image}}{{range .Mounts}} mount={{.Type}}:{{.Name}}:{{.Destination}}{{end}}' ekip-api-test ekip-api` | Confirm images and volume separation | Test mounts `ekip_task04_test_data:/app/data` and `ekip_task04_test_hf_cache:/root/.cache/huggingface`; production mounts `ekip_data:/app/data`. |
| `docker exec ekip-api-test sha256sum /app/src/api/main.py /app/src/api/tenant_storage.py /app/src/knowledge_base.py /app/src/rag_pipeline.py` and local `shasum -a 256` on same four paths | Compare running test source to working tree | All four hashes matched. No image rebuild/replacement. |
| `curl -sS -o /dev/null -w 'test API health HTTP %{http_code}\\n' http://127.0.0.1:8001/health` | Test API liveness | HTTP 200. No request was sent to port 8000. |
| Read-only Python TCP checks to `127.0.0.1:55432` and `127.0.0.1:8000` | Check service reachability | Both sockets reachable; port 8000 check only opened/closed TCP and sent no HTTP request. |
| In-process SQLAlchemy check using isolated PostgreSQL container configuration | Confirm DB identity/revision without printing URL/credentials | Database `ekip_auth_test`, revision `0004_scoped_security_audit`. No migration run. |
| In-process `httpx` live harness against `http://127.0.0.1:8001` using actual multipart `POST /documents` and JSON `POST /query` contracts | Synthetic upload, grounded answer, refusal, tenant boundary, audit and cleanup | Upload 201/1 chunk; grounded HTTP 200, `refused=false`, `evidence.sufficient=true`, one consistent citation; absent fact HTTP 200 refusal; other org had zero docs and no source/citation, cross-tenant file 404; scoped audit passed; delete 200, list empty, post-delete query refused. |
| `.venv/bin/python -m pytest tests/api/test_api_acceptance.py tests/unit/test_evidence_gate.py tests/unit/test_citation_validator.py tests/unit/test_answer_repair.py tests/unit/test_grounding_evaluator.py tests/unit/test_grounding_evaluator_uncited.py tests/unit/test_grounding_relation_guard.py tests/unit/test_grounding_support_integration.py tests/unit/test_grounding_validator.py tests/unit/test_tenant_storage.py -q` | Focused backend/API/RAG/storage regressions; avoids tests that open protected local PDFs | **72 passed in 45.76s.** |
| Read-only corrected synthetic-audit metadata query | Check organisation A and B events after initial harness assertion issue | PASS: A upload/query/delete records had correct actor, organisation, action, outcome, timestamp and minimal details. B had only its own scoped records, including its own legitimate isolation query. |
| `git diff --check` | Whitespace/error-marker check on tracked patch | Exit 0. The report itself was untracked at that moment; separate report whitespace check in the preceding work found no trailing whitespace. |

The first live harness aggregate returned false because it incorrectly expected organisation B to have no `knowledge.query` event. B correctly recorded its own cross-tenant isolation query. Read-only inspection confirmed the event was scoped to B and its actor; the corrected predicate passed. This was a harness assertion defect, not a product failure. A temporary synthetic PDF was removed; no repository `data/` was accessed.

### Previously recorded automated verification (not rerun in this continuation)

The most recent preceding Task 05 handoff records these exact outcomes; they remain historical evidence, not newly executed results:

| Command/action | Recorded result |
|---|---|
| `.venv/bin/python -m pytest tests/integration/test_auth_postgres.py -q -rs` via in-process wrapper that supplied `EKIP_TEST_DATABASE_URL` from the existing isolated PostgreSQL service | **6 passed** (latest reported `1.28s`), at migration `0004_scoped_security_audit`; secret URL not printed. A direct invocation without the guard variable produced one module skip and exit 5 (`EKIP_TEST_DATABASE_URL is not configured`). |
| `.venv/bin/pytest -q tests/unit/test_auth_access_tokens.py tests/unit/test_auth_bootstrap.py tests/unit/test_auth_database.py tests/unit/test_auth_migration.py tests/unit/test_auth_models.py tests/unit/test_auth_passwords.py tests/unit/test_auth_permissions.py tests/unit/test_auth_service.py tests/unit/test_tenant_storage.py tests/unit/test_document_fingerprints.py tests/unit/test_document_records.py tests/unit/test_rwlock.py tests/api/test_api_acceptance.py` | **112 passed in 18.90s** as recorded in the earlier handoff. The old report also records a prior 111-pass rerun after test assertion fixes; this count discrepancy was not independently re-resolved in the latest continuation. Use the 72-test latest focused run above as the current reproducible regression evidence. |
| `npm test -- --reporter=dot` in `frontend/` | **4 files, 90 passed** (latest recorded preceding handoff). |
| `npm run check` in `frontend/` | **PASS**, `tsc --noEmit`, exit 0. |
| `npm run build` in `frontend/` | **PASS**, TypeScript + Vite production build; earlier output reported 38 modules transformed. |
| `EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 npm run test:e2e` and a wrapper-created synthetic isolated test reader with in-process `EKIP_E2E_LOGIN_*` variables | **2 Playwright tests passed in 2.9s**, including live login, `/auth/me`, audit denial, logout, revoked-token check, proxy smoke. Playwright emitted `NO_COLOR`/`FORCE_COLOR` warnings only. Credentials/tokens were not printed. |
| `git diff --check` | PASS, exit 0 in prior continuation. |

The latest continuation changed no application or test source, so frontend and PostgreSQL suites were not rerun solely for report packaging. Model-heavy tests that open protected `data/raw/nist_csf_2.0.pdf` and the broad evaluation benchmark were not run. No test is claimed for those paths.

## 5. Live RAG results

- **Fixture:** a tiny, clearly synthetic PDF was created under `/private/tmp`, containing a random record code and fictional color fact absent from the preexisting test knowledge base. It was parsed before upload. The exact fact text is intentionally omitted from this report; no user or production document was involved.
- **Upload:** authenticated synthetic organisation A; multipart `POST /documents`; HTTP 201 and one indexed chunk.
- **Grounded query:** asked for the unique synthetic fact. `POST /query` returned HTTP 200, `refused=false`, sufficient evidence, and an answer supported by the uploaded source. The one citation's source number matched the corresponding ranked `source_map`, `sources[number - 1]`, and available source/page/chunk metadata. No local filesystem path was displayed as evidence.
- **Insufficient evidence:** a question about an absent value returned HTTP 200 with `refused=true` and `evidence.sufficient=false`.
- **Tenant isolation:** synthetic organisation B listed zero documents; its query for A's fact refused and contained no sources or citations; B's request for A's file returned 404.
- **Audit:** upload, query and delete events were scoped to A and its actor with action, outcome and timestamp. Details were limited to operational metadata and did not include the question or document text. B's own isolation query had its own correctly scoped event.
- **Cleanup:** the synthetic PDF was deleted using authenticated tenant-scoped `DELETE /documents/{document_id}` (HTTP 200); list became empty and post-delete query refused. The temporary local PDF was removed. Synthetic organizations/users/audit rows and empty per-organisation workspaces were intentionally retained to preserve audit attribution and avoid direct volume-level cleanup. No preexisting records or volumes were deleted.
- **Limitations:** live test exercised actual model-backed generation, grounding and citation validation on the test API. It was a single synthetic scenario, not a model benchmark or broad quality evaluation.

## 6. Git and change inventory

- Branch `feature/organisation-knowledge-management`; baseline/current commit `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b` (no commit created during this work).
- Dirty working tree. `git diff --stat` at review start: **22 tracked files changed, 1,955 insertions, 1,080 deletions**. Staged diff was empty. This aggregate includes preserved Task 04 and earlier Task 05 work and is not a Task 05.2-only attribution.
- Latest live RAG verification did not modify application source, tests, Docker resources, or data. The report and review artifacts are untracked documentation additions.
- Tracked modified paths: `.gitignore`, `Dockerfile`, `README.md`, `frontend/package-lock.json`, `frontend/package.json`, `frontend/src/App.test.tsx`, `frontend/src/App.tsx`, `frontend/src/Workspace.test.tsx`, `frontend/src/Workspace.tsx`, `frontend/src/api/client.test.ts`, `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/styles.css`, `frontend/src/test-fixtures/README.md`, `frontend/vite.config.ts`, `requirements.docker.txt`, `requirements.txt`, `src/api/main.py`, `src/knowledge_base.py`, `src/rag_pipeline.py`, `src/retrieval/reranked_retriever.py`, `tests/api/test_api_acceptance.py`.
- Other untracked relevant source/config/test paths include `Dockerfile.task05-test`, `alembic.ini`, `docs/task05_identity_database.md`, `frontend/README.md`, `frontend/e2e/`, `frontend/playwright.config.ts`, `frontend/public/`, new frontend auth/library/routing components and tests, `migrations/`, `src/api/shared_inference.py`, `src/api/tenant_storage.py`, `src/auth/`, `tests/integration/`, and auth/tenant unit tests.
- `HANDOFF_REPORT.md` (Task 04) is preserved and not rewritten. The untracked `data/` directory was not opened, altered, or packaged. No files were removed by the latest continuation.

## 7. Acceptance criteria matrix

The detailed matrix, with implementation evidence, method, outcome, outstanding issue, and closure state, is in `TASK05_2_ACCEPTANCE_AND_TEST_MATRIX.md` and included in the review ZIP.

## 8. Known limitations and outstanding work

| Severity | Item | Consequence / next action | Release blocker? |
|---|---|---|---|
| Medium | Access/refresh tokens are in memory; reload requires sign-in; refresh coordination is per tab | Consider a reviewed secure persistence/cross-tab design before broader deployment; do not store tokens in localStorage by default. | No for this MVP; required before UX expectations include reload persistence. |
| Medium | No broad RAG benchmark/evaluation run | Single live success/refusal does not establish general answer quality. Run approved evaluation later against safe fixtures without opening protected local data. | No for Task 05.2 functional gate; yes for any claim of production-quality model performance. |
| Medium | Test-only live evidence, no production deployment | Production rollout, production DB migration, operational monitoring, backup/restore and model capacity were not exercised. | Yes for production release, not for closing this isolated MVP increment. |
| Low | Synthetic identities, audit rows, and empty workspace directories remain in isolated test services | They preserve audit attribution; remove later only with a separately reviewed, scoped test-data retention procedure. | No. |
| Low | Historical report previously had contradictory states and a backend count discrepancy (111 vs 112) | This consolidated report supersedes those statements; latest focused suite is 72 passed. Re-run the larger suite if its exact count is required for a release record. | No for present evidence; do not cite the historical count as freshly rerun. |
| Low | No validated PDF renderer was used | Markdown is the source-of-truth deliverable. PDF is optional and omitted. | No. |

## 9. Final Gate A / Task 05.2 decision

| Gate | Result | Basis |
|---|---|---|
| Identity, permissions, and PostgreSQL migration chain | PASS | Code/tests and latest DB revision inspection; previous guarded PostgreSQL suite recorded 6 passed. |
| Authenticated API, `/auth/me`, logout and session revocation | PASS | Earlier live Playwright login/profile/logout/revoked-token evidence on isolated API plus API regression coverage. |
| Tenant-scoped storage, document operations and retrieval | PASS | Regression suite plus live two-organisation verification. |
| Grounding, citation consistency, and insufficient-evidence refusal | PASS | Live synthetic API scenario and 72 focused regression tests. |
| Scoped audit and authorization | PASS | Live read-only audit validation and earlier API/Playwright denial tests. |
| Frontend tests, TypeScript, build and Playwright | PASS (historical preceding run) | 90 Vitest tests, type check, production build, and 2 Playwright tests are recorded above; not rerun in the latest continuation. |
| Operational production deployment and broad model quality | NOT VERIFIED | Not part of this isolated verification; production resources were deliberately left untouched. |
| **Task 05.2 MVP closure** | **PASS, subject to review** | All currently defined Task 05.2 functional/security acceptance areas have implementation and test/live evidence. Do not interpret as production release approval. |

Task 06 may begin as a separate planned task after this handoff is reviewed. Task 06 remains **PLANNED / NOT IMPLEMENTED**. Preserve its proposed configurable metadata framework and agreed design requirements in the original roadmap; no Task 06 source change is included here.

## 10. Exact continuation instructions

1. Review `HANDOFF_REPORT_TASK05.md`, `TASK05_2_ACCEPTANCE_AND_TEST_MATRIX.md`, and the diff/archive against the current branch. The original Master Checklist v3.8 and reference addendum were not found in this repository snapshot; the separate status addendum is explicitly non-destructive and does not replace either original.
2. Keep test API at `127.0.0.1:8001`, test PostgreSQL at `127.0.0.1:55432`, and production API/`ekip_data` at port 8000 untouched. Do not print `.env`, database URLs, credentials or tokens.
3. For backend regression reproduction, run the 72-test command in §4 from the repository root. For PostgreSQL, use `tests/integration/test_auth_postgres.py` with the established in-process isolated test DB wrapper; direct pytest without `EKIP_TEST_DATABASE_URL` deliberately skips collection and exits 5.
4. Frontend checks, if needed, run from `frontend/`: `npm test -- --reporter=dot`, `npm run check`, `npm run build`, and `EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 npm run test:e2e`. The Playwright config rejects production port 8000.
5. Any future cleanup must target only the synthetic identities and empty workspaces created for this live test, preserve audit referential integrity, and be reviewed before direct database or volume operations.
6. Continue with a distinct Task 06 design/implementation request only after review; its configurable metadata framework is planned scope, not a Task 05.2 deliverable.


### Exact Git snapshot at report completion

- Branch: `feature/organisation-knowledge-management`
- HEAD: `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`
- `git diff --stat`:

```text
 .gitignore                           |   2 +
 Dockerfile                           |   2 +
 README.md                            |   9 +-
 frontend/package-lock.json           |  52 +-
 frontend/package.json                |   2 +
 frontend/src/App.test.tsx            | 240 ++++++++--
 frontend/src/App.tsx                 | 263 ++---------
 frontend/src/Workspace.test.tsx      |  11 +
 frontend/src/Workspace.tsx           |  28 +-
 frontend/src/api/client.test.ts      | 182 ++++++-
 frontend/src/api/client.ts           | 358 +++++++++-----
 frontend/src/api/types.ts            |  36 ++
 frontend/src/styles.css              | 238 +++++++++-
 frontend/src/test-fixtures/README.md |  10 +-
 frontend/vite.config.ts              |   1 +
 requirements.docker.txt              |   4 +
 requirements.txt                     |   6 +-
 src/api/main.py                      | 888 +++++++++++++++++++----------------
 src/knowledge_base.py                |  10 +
 src/rag_pipeline.py                  |  21 +-
 src/retrieval/reranked_retriever.py  |   6 +-
 tests/api/test_api_acceptance.py     | 666 ++++++++++++++++----------
 22 files changed, 1955 insertions(+), 1080 deletions(-)
```

- `git status --short` (the `data/` line is only Git's untracked-path indicator; its contents were not read or packaged):

```text
 M .gitignore
 M Dockerfile
 M README.md
 M frontend/package-lock.json
 M frontend/package.json
 M frontend/src/App.test.tsx
 M frontend/src/App.tsx
 M frontend/src/Workspace.test.tsx
 M frontend/src/Workspace.tsx
 M frontend/src/api/client.test.ts
 M frontend/src/api/client.ts
 M frontend/src/api/types.ts
 M frontend/src/styles.css
 M frontend/src/test-fixtures/README.md
 M frontend/vite.config.ts
 M requirements.docker.txt
 M requirements.txt
 M src/api/main.py
 M src/knowledge_base.py
 M src/rag_pipeline.py
 M src/retrieval/reranked_retriever.py
 M tests/api/test_api_acceptance.py
?? Dockerfile.task05-test
?? HANDOFF_REPORT.md
?? HANDOFF_REPORT_TASK05.md
?? TASK05_2_ACCEPTANCE_AND_TEST_MATRIX.md
?? TASK05_2_CHANGE_INVENTORY_AND_CONTINUATION.md
?? TASK05_2_IMPLEMENTATION_REPORT.md
?? TASK05_2_REVIEW_ARCHIVE_README.md
?? TASK05_2_STATUS_ADDENDUM.md
?? alembic.ini
?? data/
?? docs/task05_identity_database.md
?? ekip-task04-test-docker.sh
?? frontend/README.md
?? frontend/e2e/
?? frontend/playwright.config.ts
?? frontend/public/
?? frontend/src/AppShell.tsx
?? frontend/src/AuthContext.tsx
?? frontend/src/DocumentLibrary.test.tsx
?? frontend/src/DocumentLibrary.tsx
?? frontend/src/Icons.tsx
?? frontend/src/KnowledgeBaseContext.tsx
?? frontend/src/LoginPage.tsx
?? frontend/src/routing.ts
?? frontend/src/test-fixtures/documents-empty.README.md
?? frontend/src/test-fixtures/documents-empty.json
?? frontend/src/test-fixtures/query-empty-refusal.json
?? migrations/
?? src/api/shared_inference.py
?? src/api/tenant_storage.py
?? src/auth/
?? tests/integration/
?? tests/unit/test_auth_access_tokens.py
?? tests/unit/test_auth_bootstrap.py
?? tests/unit/test_auth_database.py
?? tests/unit/test_auth_migration.py
?? tests/unit/test_auth_models.py
?? tests/unit/test_auth_passwords.py
?? tests/unit/test_auth_permissions.py
?? tests/unit/test_auth_service.py
?? tests/unit/test_tenant_storage.py
```

## Run A — Task 05 audit fixes (2026-10-17, run `runa-20261017T020841`)

Appended section; the content above is unchanged. Full details are in `HANDOFF_REPORT_TASK05_runa-20261017T020841.md`, and the live-check procedure is in `docs/task05_run_a_live_verification.md`.

- **Scope and authorisation:**
  - Fixes F1–F4, B1–B7 and P1–P4, done test-first, under **Option C**: `ekip-api-test` and its volumes were not touched.
  - No commits, tags or `task05-pre-audit` tag: the owner did not authorise Git actions.
  - HEAD remains `eeb3a1b`; nothing is staged.
- **Binding-document limitation:** `docs/security/EKIP_Task_05_Implementation_Proposal_v2.md` is missing, so proposal compliance is **NOT VERIFIED**.
- **Backend:** sandboxed with offline models and the approved 35-test protected-data exclusion; baseline **296 passed** → final **331 passed**, 1 skipped (PostgreSQL module, run separately), 15 deselected, 0 failed.
- **PostgreSQL integration** (isolated, 55432): **6 passed**.
- **Frontend:** Vitest **90 (historical) → 101 passed** (6 of 6 runs); `npm run check` PASS; `npm run build` PASS.
  - Existing App and library tests got fixture-only updates for the intended F2 behaviour (authenticated `/api/auth/me` answer; two timing waits); no assertion was removed or loosened.
- **E2E:** compiled only (`playwright test --list`, 5 tests). Live test-container rebuild and Playwright: **NOT VERIFIED** (Option C).
- **111 vs 112:** the historical 13-file command gives 120 before Run A. The growth is consistent with tests added after those runs, but the exact difference can't be recovered (files never committed).
- **F3:** documented fallback (no single-use ticket; follow-up).
- **Port 8000 (read-only):** `ekip-api` listens on `0.0.0.0:8000` and `[::]:8000`. Flagged for the owner; not changed.
- **Deployment note (B4):** the API now refuses to start without `EKIP_ACCESS_TOKEN_SECRET` (at least 32 bytes).
- **New optional settings:** `EKIP_ARGON2_MAX_CONCURRENCY` (default 4), `EKIP_ENABLE_API_DOCS` (off), `EKIP_DEBUG_RETRIEVAL_LOGGING` (off).
- **Security note:** throttling is in-process (single worker) and keyed on the direct client address; behind a reverse proxy it needs trusted client-address handling first.
- **Decision:** Run A implementation complete, with automated and PostgreSQL verification PASS. Live and browser checks remain NOT VERIFIED. **Gate A has not started.**

| Item | Result | Item | Result | Item | Result |
|---|---|---|---|---|---|
| F1 | PASS (unit) | B1 | PASS | P1 | PASS |
| F2 | PASS (unit) | B2 | PASS | P2 | PASS |
| F3 | PASS (unit, fallback) | B3 | PASS | P3 | PASS |
| F4 | PASS (unit) | B4 | PASS | P4 | PASS (test only) |
| Live container + Playwright | NOT VERIFIED | B5 | PASS | | |
| | | B6 | PASS | | |
| | | B7 | PASS | | |
