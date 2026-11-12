# EKIP Task 06 — Migration Implementation and Release Plan

**Version:** 1.0
**Status:** Approved sequencing plan derived from the accepted G1 physical schema baseline.
**Scope:** Migration/service implementation sequencing, proof requirements, and recovery gates.
**Current state:** Planning artifact only; no migrations or database changes were created.

## 1. Non-negotiable gates

- **G0 — Security prerequisite:** The Task 05.3 live PostgreSQL, concurrency, and tenant-isolation verification must be explicitly signed off using the project's isolated local PostgreSQL test environment; no university deployment is required. The reported 19 passing tests from `tests/integration/test_auth_postgres.py` (including six PostgreSQL-backed API tenant-isolation tests) are evidence for the tested criteria; they do not alone prove every required Task 05.3 criterion.
- **G1 — Physical design:** The user approved the G1 recommendations on 22 October 2026. The companion `G1_PHYSICAL_SCHEMA_SPEC.md` is the working data dictionary and constraint matrix. Before DDL, reconcile its proposed names/types with the active checkout and resolve deferred items that affect DDL.
- **No migration before both gates:** Do not create or apply physical metadata migrations until G0 is signed off and the DDL review confirms G1 is complete. No production database is to be used for migration proof.

## 2. Existing migration baseline

The supplied snapshot contains the linear Alembic history:

1. `0001_identity_foundation`
2. `0002_auth_refresh_sessions`
3. `0003_auth_hardening`
4. `0004_scoped_security_audit`

Treat these four revisions as immutable. The observed disposable database `ekip_auth_test` reported `0004_scoped_security_audit` and core identity tables, but that is an observation from the user's local test environment, not permission to modify that database for arbitrary experiments. Re-check the current Alembic head and migration files in the active checkout before implementation.

## 3. Staged implementation plan

### Stage A — G0 evidence package

- Map each Task 05.3 acceptance criterion to a specific test or live verification step.
- Confirm the disposable local PostgreSQL test target, database identity, current Alembic revision, and isolation from production/application data.
- Run the required live tenant-isolation tests, including document enumeration/access by ID manipulation, tenant-context switching, concurrent authentication/session operations, and any race assertions named in Task 05.3.
- Record command, target identity, test names, pass/fail, skips, and unresolved gaps in a G0 sign-off report.
- Exit: all required criteria pass in the isolated local PostgreSQL test environment; skipped/unavailable checks are not counted as passes.

### Stage B — Physical DDL review (G1 closure)

- Compare every proposed table/column/index/constraint with active SQLAlchemy naming conventions and PostgreSQL capabilities.
- Resolve exact `NUMERIC` precision/scale from actual metadata field catalog and report/filter requirements; do not guess.
- Confirm one-published-schema-per-organisation rule before adding a partial unique index.
- Confirm field type set and whether structured JSON metadata is out of scope for initial release.
- Confirm actor deletion/retention semantics, value-state checks, vocabulary term self-reference rules, outbox claim/lease concurrency, and migration-job counters.
- Produce a migration DDL review checklist and mark each constraint as database-enforced or service-enforced with rationale.
- Exit: reviewed DDL/data dictionary, constraints, query patterns, and rollback plan accepted.

### Stage C — Disposable migration proof

Only after Stage A and B pass:

- Create or select a dedicated disposable PostgreSQL database isolated from `ekip_auth_test`, `ekip_task05_runa`, the application database, and production data.
- Capture the initial Alembic revision and schema inventory.
- Run `alembic upgrade head` from the existing `0004_scoped_security_audit` revision to the new metadata revision.
- Verify all new tables, foreign keys, checks, unique constraints, partial indexes, and expected indexes directly in PostgreSQL.
- Run migration tests from a clean database and from a copy at the current head.
- Test downgrade only on disposable data before any metadata records exist; verify restoration from backup/snapshot as a separate recovery exercise.
- Exit: upgrade/downgrade/restore evidence recorded, no existing identity tables or data unexpectedly changed.

### Stage D — Additive migration

- Add one or more new Alembic revisions after `0004_scoped_security_audit`; never rewrite 0001–0004.
- Create only metadata schema, vocabulary, document-type association, metadata value, migration-job, and outbox structures approved for the release.
- Do not create a document registry or document FK in this migration.
- Do not add speculative fields/types not required by the accepted data dictionary.
- Use deterministic constraint/index names. Make migration downgrade drop only newly created structures and only under the tested empty/unpopulated-data condition.
- Exit: migration review, disposable PostgreSQL proof, and migration test suite pass.

### Stage E — Service layer and audit transaction

- Implement tenant-scoped services before public routes rely on persistence.
- Enforce membership/role/permission and active tenant state server-side; all database reads and mutations carry authenticated tenant scope.
- Implement schema draft/publish immutability, vocabulary versioning, field validation, revision checks, and typed value persistence.
- Provide transaction-aware audit insertion that joins the caller's session without committing.
- Write value changes, required success audit event, and outbox event in one transaction.
- Ensure invitation/initial-admin lifecycle remains separate from metadata lifecycle; tenant activation follows the approved lifecycle decision.
- Exit: unit/integration tests pass for type/cardinality, tenant boundaries, optimistic concurrency, immutable versions, and audit rollback semantics.

### Stage F — Projection dispatcher and migration jobs

- Implement an idempotent CLI dispatcher for `metadata_projection_outbox`, invoked by a deployment-approved scheduler.
- Claim work safely so concurrent dispatchers do not process the same event unsafely; retries use backoff and sanitized error codes.
- Ignore stale/out-of-order metadata revisions; provide reconciliation/rebuild command and operational counters.
- Implement migration preview as read-only; apply is explicitly approved, idempotent, resumable, and bounded. Do not store private document contents in logs/errors.
- Exit: failure injection proves metadata remains committed when projection fails and retry/rebuild converges.

### Stage G — Compatibility, pilot, and retrieval integration

- Keep the current manifest-backed document lifecycle authoritative. No changes to document IDs, filenames, duplicate detection, upload/list/download/delete/restore or partial-cleanup semantics unless separately approved.
- Add tenant feature flag default OFF; enable only for a disposable/pilot organisation after security review.
- Apply metadata filters after authorization and before ranking/context generation. Current authorization remains authoritative even if an index projection is stale.
- Run existing manifest and RAG regression tests, cross-tenant retrieval tests, stale-index tests, and citation authorization tests.
- If existing-document metadata backfill is needed, use a dry-run preview, report missing/duplicate/orphan references, reconcile counts, and require explicit approval before apply.
- Exit: pilot reconciliation, regression suite, monitoring, runbook, rollback criteria, and release checklist signed.

## 4. Migration object ordering

Recommended dependency order for a future additive revision (subject to reviewed SQLAlchemy naming/types):

1. `organisation_metadata_schemas`
2. `metadata_vocabularies`
3. `metadata_vocabulary_versions`
4. `metadata_vocabulary_terms`
5. `metadata_field_definitions`
6. `metadata_document_types`
7. `metadata_document_type_fields`
8. `document_metadata_values`
9. `document_metadata_value_items`
10. `metadata_migration_jobs`
11. `metadata_projection_outbox`
12. Query indexes and any approved partial indexes

This is a dependency order, not permission to create all objects in one revision. Split revisions if review/testing shows that doing so reduces risk or supports feature staging.

## 5. Test matrix required before release

| Area | Minimum evidence |
|---|---|
| Migration | Upgrade from current head; clean database upgrade; schema inspection; safe downgrade before data; restore rehearsal |
| Tenant isolation | Tenant A cannot enumerate/access Tenant B schema, field, vocabulary, values, jobs or document by ID manipulation |
| Schema lifecycle | Draft isolation; published schema immutable; revision conflicts rejected; field keys not reused for changed meanings |
| Metadata validation | Wrong type/cardinality, invalid state, unknown/retired term, protected field mutation and required-on-save/publish rejected |
| Vocabulary | Historical term-version preserved; retired term readable historically but not assignable; ambiguous alias rejected |
| Audit | Success event and mutation commit together; audit insert failure prevents success; rollback has no false success event |
| Outbox | Duplicate delivery safe; stale revision ignored; projection failure retry converges; reconciliation detects missing projection |
| Migration jobs | Preview has no writes; apply idempotent/resumable; failures sanitized and audited; cross-tenant access denied |
| Manifest compatibility | Upload, duplicate detection, list, download, delete, restore, partial cleanup all pass |
| Retrieval | Tenant/permission filtering precedes metadata filtering, ranking and generation; citations only point to authorized documents |
| Ops/recovery | Feature disablement, backup/restore, reconciliation, retry exhaustion and rollback/forward-fix procedure rehearsed |

## 6. Rollback and recovery rules

- Before metadata data is populated, a tested downgrade may remove the new structures in disposable environments.
- After metadata data exists, prefer feature disablement and forward/compensating migrations over dropping populated tables.
- Take and verify backups before any backfill or pilot migration.
- Do not combine document-registry adoption with the first metadata migration.
- Filesystem manifest writes, database transactions, and index updates are not one atomic transaction. Preserve existing compensating cleanup semantics and add explicit operation state/reconciliation where workflows span systems.
- Never claim a rollback path is proven until the corresponding restore/downgrade rehearsal has passed.

## 7. Current checkpoint

- User approved the G1 recommendation set on 22 October 2026.
- Reported local test evidence: 15 contract tests passed; 63 lifecycle/auth tests passed; 13 PostgreSQL auth integration tests passed.
- G0 is **not formally signed off yet**: the full required Task 05.3 live tenant-isolation/concurrency evidence must be mapped to the criteria and recorded. The 13-test result is not assumed to cover every criterion.
- No metadata migration has been created or applied as part of this plan.

## 8. Next actionable work

1. Produce the G0 criterion-to-evidence matrix from Task 05.3 and existing integration tests.
2. Run only the missing checks against the approved disposable environment, with no production target.
3. Record G0 outcome honestly, including skipped checks and unresolved failures.
4. After explicit G0 sign-off, review physical DDL against the active checkout and create a new additive Alembic revision in a sandbox branch.
