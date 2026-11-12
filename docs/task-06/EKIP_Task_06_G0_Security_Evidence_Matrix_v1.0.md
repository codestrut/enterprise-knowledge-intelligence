# EKIP Task 06 — G0 Security Evidence Matrix

**Version:** 1.0
**Snapshot reviewed:** `EKIP_Task06_Current_Snapshot.zip` uploaded 2026-10-22
**Prepared:** 2026-10-22
**Status:** **G0 READY FOR LOCAL SECURITY-GATE SIGN-OFF — no university deployment is required**

## 1. Purpose and decision rule

G0 requires evidence for the existing Task 05.3 PostgreSQL, concurrency, and tenant-isolation security gate. Verification is performed against the project's isolated local PostgreSQL test container; no university deployment is required. Synthetic tests or source review alone are insufficient for database-backed claims. This matrix separates tests that have passed from the claims those results support.

No database migration or production change is authorized by this matrix.

## 2. Evidence summary

| Security area | Existing evidence in reviewed snapshot | Reported result | Environment and strength | G0 assessment |
|---|---|---|---|---|
| PostgreSQL authentication schema and persistence | `tests/integration/test_auth_postgres.py::test_postgres_auth_schema_constraints_and_new_engine_persistence`; duplicate email and persisted refresh-session/audit checks | PostgreSQL integration file: **13 passed** in user's local run on 2026-10-22 | Real PostgreSQL test container `ekip-task05-postgres-test`, database `ekip_auth_test`, revision `0004_scoped_security_audit` | **Covered for tested authentication persistence/constraints**; preserve run output as evidence |
| Refresh-session identity integrity | `test_postgres_rejects_refresh_session_user_membership_mismatch` | Included in 19-pass run | PostgreSQL integration | **Covered** for the tested FK/constraint mismatch |
| Credential verification locking | `test_postgres_credential_verification_does_not_issue_for_update`; `test_postgres_password_verification_runs_without_a_held_user_lock` | Included in 19-pass run | PostgreSQL integration with SQL/lock assertions | **Covered** for these assertions |
| Concurrent authentication | `test_postgres_concurrent_authentication_completes` | Included in 19-pass run | PostgreSQL integration | **Covered** for concurrent authentication completion |
| Refresh rotation retry idempotency | `test_postgres_concurrent_refresh_retry_with_same_key_is_idempotent` | Included in 19-pass run | PostgreSQL integration | **Covered** for same-key retry idempotency |
| Refresh-token replay, family revocation, logout races, lock ordering | `test_postgres_concurrent_different_key_replay_revokes_family_without_deadlock`; `test_postgres_refresh_after_family_logout_is_rejected`; `test_postgres_refresh_racing_family_logout_leaves_no_active_tokens`; `test_postgres_auth_database_uses_read_committed`; `test_postgres_concurrent_replay_of_two_old_tokens_revokes_family_without_deadlock`; `test_postgres_old_token_replay_racing_legitimate_refresh_leaves_family_dead`; `test_postgres_family_lock_is_taken_before_any_row_lock` | Included in 19-pass run | PostgreSQL integration with bounded lock waits and concurrent operations | **Covered** for these implemented scenarios; preserve full pytest output and revision details |
| Cross-tenant document list/download/delete and duplicate scope | `tests/api/test_api_acceptance.py::test_documents_queries_downloads_and_deletion_are_isolated_by_membership`; `test_duplicate_pdf_is_rejected_only_inside_the_authenticated_tenant` | Existing API acceptance suite is in snapshot; this matrix does not claim a new run | SQLite auth database, fake knowledge base and temporary tenant workspaces | **Synthetic/API coverage only**; not live PostgreSQL-backed tenant isolation |
| Authenticated query tenant boundary | `tests/integration/test_authenticated_query_tenant_isolation.py::test_authenticated_query_uses_only_the_current_tenant_workspace` | Existing test in snapshot | Dependency overrides and synthetic tenant workspaces; audit helpers are stubbed | **Synthetic/API-path coverage only**; not a live persisted-auth/PostgreSQL proof |
| Retrieval workspace separation and mismatch rejection | `tests/integration/test_rag_tenant_retrieval_isolation.py`; `tests/integration/test_real_tenant_index_isolation.py` | Existing tests in snapshot | In-memory/synthetic indexes; no PostgreSQL connection | **Retrieval isolation evidence only**; not live database-backed tenant isolation |
| Tenant storage directory/path isolation | `tests/unit/test_tenant_storage.py` | Existing tests in snapshot | Temporary filesystem, including path-traversal/symlink checks | **Unit-level storage evidence only** |
| Local isolated Task 05.3 PostgreSQL gate | Current local run reported 19 passing PostgreSQL integration tests; Alembic reports `0004_scoped_security_audit (head)` | 19 passed in 37.02s; saved output captured | Docker test container `ekip-task05-postgres-test`, database `ekip_auth_test`; no credentials in evidence | **Evidence captured; ready for final review and sign-off** |

## 3. What the current PostgreSQL run establishes

The current local run of `./scripts/test_postgres_integration.sh` returned `19 passed in 37.02s`. The saved output is `/tmp/ekip_task06_g0_test_evidence.log`. The isolated database is `ekip_auth_test` on the loopback-published `ekip-task05-postgres-test` container, and Alembic reports `0004_scoped_security_audit (head)`.

The 19-test suite includes the six PostgreSQL-backed API tenant-isolation tests in `tests/integration/test_auth_postgres.py`:

- `test_postgres_authenticated_document_listing_is_tenant_scoped`
- `test_postgres_authenticated_document_download_and_delete_cannot_cross_tenants`
- `test_postgres_document_delete_audit_uses_authenticated_organisation`
- `test_postgres_authenticated_query_uses_only_current_tenant_workspace`
- `test_postgres_audit_reads_are_scoped_to_authenticated_organisation`
- `test_postgres_platform_admin_flag_does_not_grant_cross_tenant_content_access`

This is live PostgreSQL evidence for the tested authentication, concurrency, and tenant-isolation behaviours. It does not establish correctness of unimplemented metadata or onboarding functionality; those require their own tests when implemented. No university deployment is part of this project's gate.

## 4. Evidence and sign-off

The local isolated PostgreSQL test environment is the designated test environment for this project. No university deployment is required.

1. Preserve the raw output for `./scripts/test_postgres_integration.sh` showing 19 passes; keep credentials out of the log.
2. Record the disposable database name `ekip_auth_test` and Alembic revision `0004_scoped_security_audit (head)`. Do not target production or `ekip_task05_runa`.
3. Confirm the same run exercised all six API-level tenant-isolation tests listed above.
4. Review the evidence and record the G0 decision. Do not claim that tests cover metadata or tenant-onboarding features that have not yet been implemented.

The tests must use unique synthetic identities and data, avoid broad cleanup statements, and never target the production `ekip-api` container or the `ekip_task05_runa` database.

## 5. Acceptance checklist

- [x] PostgreSQL auth/concurrency and API-isolation suite reported **19 passed in 37.02s** locally on 2026-10-22.
- [x] Saved test output captured at `/tmp/ekip_task06_g0_test_evidence.log` (no credentials included).
- [x] Isolated database identified as `ekip_auth_test`; Alembic revision is `0004_scoped_security_audit (head)`.
- [x] Six PostgreSQL-backed API tenant-isolation tests are present in the suite and included in the reported 19-test run.
- [x] Local isolated PostgreSQL environment is the project's test environment; university deployment is not required.
- [ ] Review and record explicit G0 sign-off.

## 6. Decision

**G0 is ready for local security-gate sign-off.** The reported 19-test PostgreSQL run, current Alembic head, and six API tenant-isolation test names are recorded above. No university deployment is required. Once the project owner records the explicit sign-off, proceed with the approved G1 schema implementation. Do not create or apply metadata migrations before that sign-off and migration review.
