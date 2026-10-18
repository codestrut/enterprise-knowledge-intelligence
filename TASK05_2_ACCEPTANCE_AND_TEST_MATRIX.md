# EKIP Task 05.2 — Acceptance and Test Evidence Matrix

Evidence snapshot: 2026-10-16. “Historical” means the outcome was recorded in the immediately preceding handoff, not rerun during the latest live-RAG continuation.

| Criterion | Implementation evidence | Verification method | Result | Outstanding issue | Closure status |
|---|---|---|---|---|---|
| Password and identity foundation | `src/auth/models.py`, `passwords.py`, `service.py`; Argon2 hashing; unique user identity and membership constraints | Auth/model/password unit tests and PostgreSQL suite (historical) | PASS; PostgreSQL suite 6 passed | None known for MVP | Closed |
| Organisation membership and role permissions | `OrganisationMembership.role`; `permissions_for_role`; `get_authenticated_context` | API/unit/PostgreSQL tests; server derives scope from active membership | PASS | Platform admin has no implicit tenant rights by design | Closed |
| Login and safe profile `/auth/me` | Routes in `src/api/main.py`; response model limits profile fields | API tests; live Playwright login/profile (historical) | PASS | None for MVP | Closed |
| Refresh and logout revocation | `src/auth/service.py`; refresh family record and revocation | Unit/PostgreSQL tests; live browser logout then protected request 401 (historical) | PASS | Cross-tab coordination not implemented/tested | Closed with limitation |
| Protected endpoints and failure paths | Permission dependencies on document/query/audit routes | API tests and live unauthenticated/denied route checks | PASS | None observed | Closed |
| Tenant document isolation | `TenantWorkspaceRegistry`, tenant manifests/uploads/indexes; legacy global data not imported | 72 focused tests; live two-organisation list/query/file denial | PASS | Production filesystem isolation not deployed/tested | Closed in isolated MVP |
| Upload/index and safe deletion | `POST /documents`, `DELETE /documents/{id}` | API tests and live synthetic PDF upload/delete | PASS; 201, then 200 delete and empty list | Synthetic auth/audit records retained | Closed |
| Grounded answer | RAG response evidence and citations | Live query against unique synthetic fact on 8001 | PASS; HTTP 200, sufficient evidence, refusal false, one consistent citation | Single scenario only | Closed for functional criterion |
| Insufficient evidence refusal | Evidence gate/refusal contract | Live absent-fact query and evidence tests | PASS; HTTP 200, refusal true, sufficient false | General benchmark quality not measured | Closed for functional criterion |
| Citation metadata consistency | Citation source number, ranked `source_map`, `sources[n-1]`, source/page/chunk metadata | Live harness validates all available records; citation validator tests | PASS | No broad adversarial citation benchmark | Closed for MVP |
| Cross-tenant query/citation/file boundary | Tenant selected from authenticated context | Live B query has no sources/citations, B list empty, A file request returns 404 | PASS | None observed | Closed in isolated MVP |
| Audit events for failed login and document/query operations | `AuditEvent`; `_start_audit_event`, `_finish_audit_event`; auth service failed-login recording | API tests, live operation rows inspected read-only | PASS; scoped actor/action/outcome/time; content omitted | Retention/rotation policy is operational follow-up | Closed for MVP |
| Audit failure behavior and reader | `_commit_audit` returns 503 on DB failure; `/audit/events` requires `audit:read` and filters tenant | API tests; live reader denial 403; live DB scope check | PASS | No alerting/retention ops verification | Closed for MVP |
| PostgreSQL migration chain | Alembic migrations 0001–0004 | Previous isolated integration run: 6 passed; latest DB revision inspection | PASS | No production migration (intentionally) | Closed for test environment |
| Frontend login/session/library | Auth context, login page, API client, workspace components | Previous Vitest 90 passed, `npm run check`, `npm run build`; Playwright 2 passed | PASS (historical) | Reload requires sign-in; per-tab refresh | Closed with limitations |
| Regression checks after latest RAG investigation | API, evidence gate, citation, repair, grounding, tenant storage | Exact focused pytest command in handoff | PASS; 72 passed in 45.76s | KnowledgeBase tests opening protected local PDF excluded | Closed for chosen safe scope |
| Production safety | No source deployment to production; port/volume inspected | Read-only container/mount checks; no HTTP to 8000 | PASS | Production acceptance intentionally not performed | Closed for this task; separate release gate |
| Broad model evaluation | None in this continuation | Not run; would read protected local benchmark files | NOT VERIFIED | Run with safe approved benchmark fixture if required | Follow-up |
| Cross-tab session refresh | No cross-tab coordination implementation | Not tested | NOT VERIFIED | Design/implement if required by UX/security requirements | Follow-up |
| Task 06 metadata framework | Not implemented | Source/status review | NOT STARTED (planned) | Begin only under Task 06 brief | Not part of Task 05.2 |
