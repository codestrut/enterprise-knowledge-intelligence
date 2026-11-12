# EKIP Task 06 — Source Audit and Implementation Checkpoint

**Snapshot reviewed:** `EKIP_Task_06_Implementation_Bundle.zip` uploaded 2026-10-21\
**Purpose:** Focused Phase 1 / D01 source-to-contract reconciliation\
**Status:** Source audit completed and a non-persistent contract-validation slice added in the sandbox. This is not a live-database sign-off or migration approval.

## Executive decision

The next safe step is **not** to add metadata tables or wire onboarding endpoints to persistence yet. Task 06's Data Model Decision Record v1.1 explicitly requires the Task 05.3 live PostgreSQL, concurrency, and tenant-isolation gate (G0) and final physical-schema decisions (G1) before new additive Alembic migrations are created. As a non-persistent first coding slice, this checkpoint adds strict Pydantic request-contract models and unit tests; these models do not create tenants, mutate data, or expose routes.

The supplied bundle supports the Phase 1 architecture/API gap map and contract-validation groundwork. It does not establish the live database revision or prove the G0 gate has passed. Feature implementation that depends on new persisted onboarding/metadata state should follow those gates rather than inventing a provisional schema.

## 1. Source-verified current state

### Existing identity and access foundation

`src/auth/models.py` defines SQLAlchemy models for:

- `Organisation`
- `User`
- `OrganisationMembership`
- `RefreshSessionRecord`
- `AuditEvent`

The existing permission model is in `src/auth/permissions.py`. The audit model is `auth_audit_events`; migration `0004_scoped_security_audit.py` adds its nullable organisation scope. Existing identity tables should be reused; Task 06 does not need duplicate identity or audit subsystems.

The supplied migration chain is linear:

`0001_identity_foundation` → `0002_auth_refresh_sessions` → `0003_auth_hardening` → `0004_scoped_security_audit`

`migrations/env.py` targets `Base.metadata`. This verifies the migration files in the bundle, **not** the current revision or schema state of any live database.

### Existing document and retrieval foundation

`src/api/tenant_storage.py` uses `TenantWorkspaceRegistry` keyed by a validated organisation UUID. Each workspace owns its document root, upload directory, manifest and retrieval state. The manifest is JSON (`documents_manifest.json`) and is written through a temporary file followed by `os.replace`.

The Task 06 Data Model Decision Record v1.1 says to retain the manifest for existing document-record, lifecycle, duplicate-detection and recovery responsibilities until a separate relational document-registry decision is approved. No relational document table was found in the supplied `src/` and `migrations/` files. Metadata values must therefore use an application-level document identifier plus server-side tenant ownership validation for the initial design; do not add a document FK prematurely.

### Existing API surface

The route inventory in `src/api/main.py` includes:

- Authentication: `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/me`
- Audit: `/audit/events`
- Tenant status: `/tenant/status`
- Documents: `/documents`, document file download, document deletion
- Knowledge Q&A: `/query`
- Health: `/health`

No tenant registration, platform organisation provisioning/activation, invitation, metadata schema, vocabulary, document-metadata, or metadata migration routes were found in the supplied active `src/api/main.py`. A search of the supplied Python source did not find existing implementations for those Task 06 API families, an onboarding provisioning state machine, or an outbox/worker abstraction. This finding is limited to the supplied bundle and searched source tree.

## 2. Task 06 contract-to-code gap matrix

| Capability | Current evidence in supplied bundle | Gap / disposition |
|---|---|---|
| Identity, memberships, roles | Existing models and permission service | Reuse; extend only when an approved requirement needs it |
| Tenant document isolation | UUID-scoped workspace registry and tenant tests exist | Preserve; must still pass live PostgreSQL/concurrency gate |
| Registration requests and email verification | No matching route or persistence model found | Missing; depends on lifecycle and persistence design |
| Platform approval, tenant provisioning and retries | No matching routes/state machine found | Missing; define durable state and idempotency before implementation |
| Initial administrator activation | Decision record exists; no corresponding routes found | Missing; activation must recheck server-side predicates |
| Invitations and acceptance | No matching routes or invitation model found | Missing; hashed single-use token, recipient binding, expiry and concurrency controls required |
| Metadata schema and field definitions | No metadata models/migrations/routes found | Missing; G1 must freeze physical model first |
| Vocabularies and document types | No metadata implementation found | Missing; version and retirement semantics must be decided |
| Per-document metadata values | No metadata implementation found; document registry is manifest-backed | Missing; tenant ownership must be checked in application service |
| Metadata-aware library and retrieval | Existing document/Q&A path only; no metadata integration found | Later phase; untagged documents must remain discoverable and authorization must precede reranking/generation/citation |
| Audit for onboarding and metadata lifecycle | Existing `AuditEvent`; helpers in `src/api/main.py` commit independently | Extend carefully; successful metadata mutation and required audit should share one transaction where feasible |
| Durable metadata index refresh | In-memory retrieval/index components; no worker/outbox found in searched source | Open G1 design decision; metadata commit must survive projection failures |
| Proactive advisory | No Task 06 implementation found | Later, opt-in phase; not a prerequisite for first usable metadata release |

## 3. Mandatory gates and open design decisions

### G0 — prerequisite security verification

The Task 05.3 G0 gate is verified using the project's isolated local PostgreSQL test environment and requires explicit sign-off. No university deployment is required. Synthetic tests alone are not sufficient. The sandbox could not reproduce the live PostgreSQL run because its live prerequisites were unavailable. In the user's local environment, the current suite subsequently reported 19 passed in 37.02s, the six API tenant-isolation tests were confirmed present, and Alembic reported `0004_scoped_security_audit (head)`. The evidence is ready for local G0 sign-off; no university deployment is required.

### G1 — finalize physical schema before migration

The current decision record explicitly leaves these decisions open:

1. **Metadata value storage:** select validated canonical JSON/JSONB versus typed value storage based on expected filter, sort and reporting workloads. Define type/cardinality/size/depth and missing/null/empty semantics.
2. **Vocabulary versioning:** choose a separate version entity or a version column while preserving historical interpretation.
3. **Document type required fields:** choose a normalized association if required-field rules vary by document type/schema.
4. **Index refresh reliability:** inspect deployment/runtime and choose a durable retry marker or outbox based on available worker topology.
5. **Failure audit policy:** distinguish successful mutation audit (transactional where feasible) from durable logging of failed operations.
6. **Document registry:** separate decision with stable IDs, organisation-scoped uniqueness, backfill, deletion semantics and cutover.
7. **Live database state:** verify the actual Alembic revision and drift in the isolated local PostgreSQL test database.

### G2 — disposable database proof

After G0 and G1, use a disposable PostgreSQL database to verify upgrade from the existing head, constraints/indexes, safe downgrade where feasible, and restore/recovery. No production migration should be attempted as part of this checkpoint.

## 4. Sandbox implementation slice

Added `src/api/task06_contracts.py` with strict, extra-forbidden Pydantic request models for public registration, email verification, platform-led organisation creation, registration review/rejection, activation approval, suspension, invitations, and provisioning retries. Inputs normalize organisation slugs and email addresses, bound request fields, reject unsupported tenant-role values, mask verification/invitation tokens, and require a selector for provisioning retries.

Added `tests/unit/test_task06_contracts.py` covering normalization, malformed input, forbidden extra fields, secret-token serialization, role validation, and retry-selector requirements. These are request contracts only: no API routes, persistence models, background jobs, or database migrations are added in this tranche. Email validation is syntactic only; the eventual registration workflow must perform verification and abuse throttling server-side.

## 5. Sandbox test evidence

The following focused tests were run against the extracted bundle:

| Test | Result |
|---|---|
| `tests/unit/test_task06_contracts.py` | **Passed** — 15 tests |
| `tests/unit/test_auth_models.py` | **Passed** — 9 tests |
| `tests/unit/test_auth_permissions.py` | **Passed** — 8 tests |
| `tests/unit/test_auth_service.py` | **Passed** — 16 tests |
| `tests/unit/test_auth_migration.py` | **Passed** — 5 tests |
| `tests/integration/test_auth_postgres.py` | **Sandbox skipped** — live PostgreSQL prerequisites unavailable; local run subsequently reported 19 passed in 37.02s |
| `tests/unit/test_tenant_storage.py` | **Could not collect** — sandbox lacks `sentence_transformers` |

The Python runtime emitted an unrelated spreadsheet-runtime warmup diagnostic before pytest output. It did not prevent the four focused unit suites above from passing. No live database, external service, or production resource was accessed.

## 6. Recommended implementation sequence

1. **Complete G0 using the isolated local PostgreSQL test environment** and capture the database revision plus PostgreSQL/concurrency/tenant-isolation evidence.
2. **Resolve G1** and freeze the physical data dictionary, constraints and migration plan. Keep existing migrations `0001`–`0004` unchanged.
3. **Build additive persistence and service layer** for metadata schema/versioning, fields, document types, vocabularies and values, with tenant-scoped constraints and transaction-aware audit.
4. **Implement onboarding state machine and APIs** for self-service registration plus platform-admin-led creation, email verification, approval, provisioning/retries, initial-admin invitation/activation, suspension and idempotency.
5. **Add tenant-console and metadata UI** only after API contracts are implemented and tested.
6. **Integrate metadata into the document library and retrieval** without excluding untagged documents or weakening existing permission checks.
7. **Complete migration, security, regression and release evidence**; defer proactive advisory until its phase.

## Scope and limitations

This audit was performed against the uploaded ZIP, not the user's live Mac checkout or live PostgreSQL instance. It does not prove the current local working tree is identical to the uploaded snapshot. The report is a Phase 1/D01 checkpoint and gap map, not a claim that Task 06 is complete.


## 7. Updated onboarding implementation decisions — 2026-10-22

- **G0:** project owner approved explicit G0 sign-off on 2026-10-22 based on the recorded isolated PostgreSQL evidence. No university deployment is required. This does not claim that the new onboarding migrations have been applied or validated against PostgreSQL.
- **Platform authorization:** use explicit platform-scoped role profiles, distinct from organisation membership roles: `platform_super_administrator`, `platform_tenant_creator`, `platform_tenant_approver`, and `platform_provisioning_operator`. A user may hold multiple roles; creator and approver may be the same person when assigned permissions authorize both actions. Audit this as `creator_also_approver`, not as a separation-of-duties exception.
- **Legacy compatibility:** `users.is_platform_admin` temporarily resolves to the super-administrator permission bundle. New role assignments are persisted separately and granted only by an actor with `platform-roles:assign`. Plan a future removal of the legacy boolean rather than silently changing existing operators' access.
- **Provisioning recovery:** persist `provisioning_started_at`; an authorized recovery operation locks the onboarding row and marks an in-flight attempt failed only after the 15-minute stale threshold. Recovery does not perform external workspace operations while holding the row lock. A separate authorized retry reuses the idempotent workspace provisioner. Attempts are capped at five before operator review.
- **Additive migration:** `0006_platform_roles_and_recovery` follows `0005_tenant_onboarding` and adds `platform_role_assignments` plus `tenant_onboarding.provisioning_started_at`. Do not apply either migration until both pass review and disposable PostgreSQL validation.
- **Validation status:** focused sandbox tests pass (68 passed on 2026-10-22); offline SQL generation passes through revision 0006. Live PostgreSQL migration and concurrency proof remain open.
