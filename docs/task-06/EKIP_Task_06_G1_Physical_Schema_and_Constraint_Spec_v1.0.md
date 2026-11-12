# EKIP Task 06 — G1 Physical Schema and Constraint Specification

**Version:** 1.0
**Decision status:** Approved working design baseline, 22 October 2026
**Approval scope:** The G1 recommendations accepted by the user in chat.
**Implementation status:** Specification only. No SQLAlchemy models, DDL, Alembic revision, or database was changed.
**Hard gate:** Do not create or apply physical DDL/migrations until G0 is explicitly signed off after the required Task 05.3 live PostgreSQL, concurrency, and tenant-isolation verification.

## 1. Purpose and source boundary

This document turns the accepted G1 recommendations into a physical-schema specification that can be reviewed before migration implementation. It is based on the supplied Task 06 source bundle and the following design records:

- `EKIP_Task_06_Data_Model_Decision_Record_v1.1_2026-10-21.pdf`
- `EKIP_Task_06_Logical_Data_Model_Migration_Blueprint_v1.0_2026-10-20.pdf`
- `EKIP_Task_06_API_Contract_Data_Model_Proposal_v1.0_2026-10-20.pdf`
- `EKIP_Task_06_Metadata_API_Contracts_v1.0_2026-10-20.docx`
- `EKIP_Task_06_Initial_Admin_Activation_Decision_v1.0_2026-10-20.pdf`

The supplied source snapshot has SQLAlchemy identity models with UUID identifiers, PostgreSQL/Alembic history through `0004_scoped_security_audit`, and manifest-backed document identity. These are snapshot findings, not a fresh inspection of the user's live checkout.

## 2. Approved design decisions

1. Governed metadata values use typed relational value items; JSON is not the sole representation for core values.
2. A value set has one parent row and zero or more ordered item rows. Multi-value cardinality is explicit.
3. Missing, unknown, not-applicable, and not-yet-reviewed are distinct states. They are not interchangeable with SQL `NULL` or empty strings.
4. Vocabulary identity is separate from immutable vocabulary versions. Metadata values preserve the exact term-version reference.
5. Document-type-to-field associations are normalized relational rows scoped to the schema version.
6. No relational document registry or document foreign key is introduced in the first metadata migration. `document_id` remains an application-level reference checked through the authenticated tenant's existing document manifest/workspace.
7. Successful metadata mutation, required success audit event, and outbox/projection event commit in one transaction.
8. Durable projection retries use a PostgreSQL outbox plus a small idempotent CLI dispatcher. No in-memory queue is authoritative.
9. Tenant scope is enforced in service authorization and composite relational constraints wherever PostgreSQL can enforce it.
10. Draft/value-set updates use optimistic revision checks. Published schema and vocabulary versions are immutable.

## 3. Common conventions

- Primary identifiers: PostgreSQL UUID, matching existing identity models.
- Tenant scope: `organisation_id UUID NOT NULL` on every tenant-owned metadata table.
- Timestamps: `TIMESTAMPTZ NOT NULL DEFAULT now()` for persisted event times.
- Actors: reference existing `users.id` where an actor is required; decide `ON DELETE` only after reviewing retention requirements. Existing identity rows are currently protected by `RESTRICT` in several relationships.
- Mutable records: `revision INTEGER NOT NULL DEFAULT 1`, incremented on accepted mutation. Reject a stale `expected_revision` with a conflict response.
- Lifecycle enums: use named, validated strings/SQLAlchemy non-native enums consistent with current identity-model style unless a reviewed reason requires PostgreSQL native enums.
- Names below are proposed canonical names. Before implementation, reconcile every identifier with existing naming conventions and avoid collision with the active checkout.
- No tenant identity is trusted from the request body. Derive it from the authenticated principal and active membership.

## 4. Table specification

### 4.1 `organisation_metadata_schemas`

| Column | Type | Null | Rule / purpose |
|---|---|---:|---|
| `id` | UUID | no | Primary key |
| `organisation_id` | UUID | no | FK to `organisations.id`; tenant owner |
| `version` | INTEGER | no | Positive schema version |
| `status` | VARCHAR(20) | no | `draft`, `published`, `retired` |
| `name` | VARCHAR(200) | no | Non-empty display name |
| `description` | TEXT | yes | Human-readable purpose |
| `revision` | INTEGER | no | Optimistic concurrency; starts at 1 |
| `created_by_user_id` | UUID | no | FK to `users.id` |
| `published_by_user_id` | UUID | yes | FK to `users.id` |
| `created_at`, `updated_at` | TIMESTAMPTZ | no | Creation/update times |
| `published_at`, `retired_at` | TIMESTAMPTZ | yes | Lifecycle timestamps |
| `change_summary` | TEXT | yes | Required on publication if contract policy says so |

Constraints: PK `id`; unique `(organisation_id, version)`; unique `(id, organisation_id)` to support tenant-safe composite FKs; `version > 0`; `revision > 0`; non-empty trimmed name. If only one published schema per organisation is a product invariant, add a PostgreSQL partial unique index on `organisation_id WHERE status = 'published'`. Published rows are immutable; publication must not mutate a published version in place.

### 4.2 `metadata_field_definitions`

| Column | Type | Null | Rule / purpose |
|---|---|---:|---|
| `id` | UUID | no | Primary key |
| `organisation_id` | UUID | no | Tenant scope |
| `schema_id` | UUID | no | FK to schema in same organisation |
| `field_key` | VARCHAR(100) | no | Stable normalized key; never reused for a different meaning |
| `label` | VARCHAR(200) | no | Display label |
| `description` | TEXT | yes | Field guidance |
| `value_type` | VARCHAR(24) | no | Enumerated type defined in §5 |
| `cardinality` | VARCHAR(12) | no | `single` or `multiple` |
| `required_on_save` | BOOLEAN | no | Default false |
| `required_on_publish` | BOOLEAN | no | Default false |
| `visibility` | VARCHAR(20) | no | Contract-approved visibility values |
| `filterable` | BOOLEAN | no | Default false; explicit opt-in |
| `sortable` | BOOLEAN | no | Default false; only supported types |
| `is_protected` | BOOLEAN | no | System/protected field guard |
| `validation_rules` | JSONB | no | Declarative validated rules only; never executable code |
| `vocabulary_version_id` | UUID | yes | Required for vocabulary-backed field types |
| `display_order` | INTEGER | no | Default 0 |
| `created_at`, `updated_at` | TIMESTAMPTZ | no | Audit timestamps |

Constraints: unique `(schema_id, field_key)`; unique `(id, schema_id, organisation_id)` where needed for composite FKs; composite FK `(schema_id, organisation_id)` to schema `(id, organisation_id)`; non-empty field key/label; valid value type/cardinality; `required_on_save` and `required_on_publish` are independent. Protected EKIP fields cannot be removed, retyped, or have validation weakened through tenant configuration. Field keys are not reused for different semantics across schema versions; service validation enforces the rule across versions.

### 4.3 `metadata_document_types`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `schema_id UUID NOT NULL`, `type_key VARCHAR(100) NOT NULL`, `label VARCHAR(200) NOT NULL`, `description TEXT NULL`, `status VARCHAR(20) NOT NULL`, `display_order INTEGER NOT NULL DEFAULT 0`, timestamps, optional creator actor.

Constraints: unique `(schema_id, type_key)`; unique `(id, schema_id, organisation_id)`; composite FK `(schema_id, organisation_id)` to schema; valid status; non-empty key/label. A document type is defined within a schema version and does not silently drift when a new schema is published.

### 4.4 `metadata_document_type_fields`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `schema_id UUID NOT NULL`, `document_type_id UUID NOT NULL`, `field_definition_id UUID NOT NULL`, `required_on_save BOOLEAN NULL`, `required_on_publish BOOLEAN NULL`, `display_order INTEGER NOT NULL DEFAULT 0`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.

Constraints: unique `(document_type_id, field_definition_id)`; composite FKs ensure the document type and field belong to the same schema and organisation. `NULL` override means inherit the field definition's setting; an override may only be accepted if the API contract permits it. Do not store the association solely as a JSON array.

### 4.5 `metadata_vocabularies`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `vocabulary_key VARCHAR(100) NOT NULL`, `display_name VARCHAR(200) NOT NULL`, `description TEXT NULL`, `status VARCHAR(20) NOT NULL`, timestamps, optional creator actor.

Constraints: unique `(organisation_id, vocabulary_key)`; unique `(id, organisation_id)`; tenant FK to organisations; non-empty normalized key and display name. Vocabulary identity is stable; content lives in version rows.

### 4.6 `metadata_vocabulary_versions`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `vocabulary_id UUID NOT NULL`, `version INTEGER NOT NULL`, `status VARCHAR(20) NOT NULL`, `created_by_user_id UUID NOT NULL`, `approved_by_user_id UUID NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `published_at TIMESTAMPTZ NULL`, `retired_at TIMESTAMPTZ NULL`, optional `change_summary TEXT`.

Constraints: unique `(vocabulary_id, version)`; unique `(id, organisation_id)`; composite FK `(vocabulary_id, organisation_id)` to vocabulary; positive version. Published versions are immutable. Publication and approval transitions must be concurrency-safe.

### 4.7 `metadata_vocabulary_terms`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `vocabulary_version_id UUID NOT NULL`, `term_key VARCHAR(100) NOT NULL`, `label VARCHAR(200) NOT NULL`, `aliases JSONB NOT NULL DEFAULT '[]'`, `parent_term_id UUID NULL`, `status VARCHAR(20) NOT NULL`, `display_order INTEGER NOT NULL DEFAULT 0`, timestamps.

Constraints: unique `(vocabulary_version_id, term_key)`; composite FK to version and organisation; optional parent reference must remain inside the same vocabulary version; non-empty key/label; `aliases` must be a JSON array of strings enforced by service validation and a DB check where supported. Retire, do not hard-delete, terms that have historical value references. Aliases assist search/matching only and do not confer authorization. Ambiguous aliases must not be silently resolved.

### 4.8 `document_metadata_values`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `document_id VARCHAR(200) NOT NULL`, `schema_id UUID NOT NULL`, `field_definition_id UUID NOT NULL`, `value_state VARCHAR(24) NOT NULL`, `provenance JSONB NOT NULL DEFAULT '{}'`, `revision INTEGER NOT NULL DEFAULT 1`, `created_by_user_id UUID NOT NULL`, `updated_by_user_id UUID NOT NULL`, timestamps.

Unique `(organisation_id, document_id, schema_id, field_definition_id)`. Composite FKs ensure schema and field definition belong to the same organisation/schema. `document_id` is an application-level reference only in this rollout: resolve it through the authenticated organisation's existing manifest/workspace before every read/write. No FK to a document table is allowed in this migration set.

`value_state` allowed values: `known`, `unknown`, `not_applicable`, `not_yet_reviewed`. No row means missing. A row with `unknown`, `not_applicable`, or `not_yet_reviewed` has no value items. `known` has one or more items for `single` and `multiple` cardinalities, except a multi-valued field may use an explicitly permitted empty set only if the API contract defines that as semantically different from missing. Default policy: empty known sets are rejected. Empty strings are rejected unless an explicit field policy allows them.

### 4.9 `document_metadata_value_items`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `value_set_id UUID NOT NULL`, `ordinal INTEGER NOT NULL`, `value_type VARCHAR(24) NOT NULL`, nullable typed slots `text_value TEXT`, `integer_value BIGINT`, `decimal_value NUMERIC`, `boolean_value BOOLEAN`, `date_value DATE`, `datetime_value TIMESTAMPTZ`, `vocabulary_term_id UUID NULL`, and optional `json_value JSONB` only for a separately approved structured field type.

Constraints: unique `(value_set_id, ordinal)`; composite FK to value set/organisation; `ordinal >= 0`; CHECK that exactly one compatible typed slot is populated for a known item. Vocabulary references must point to the exact term-version row. The service validates compatibility between the item slot and immutable field definition, cardinality, vocabulary status, and state. Exact decimal precision/scale and structured JSON types remain intentionally deferred until the field catalog and reporting/filter workloads are approved; do not guess a precision default.

### 4.10 `metadata_migration_jobs`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `source_schema_id UUID NOT NULL`, `target_schema_id UUID NOT NULL`, `status VARCHAR(24) NOT NULL`, `idempotency_key VARCHAR(200) NOT NULL`, `selection_spec JSONB NOT NULL`, `mapping_spec JSONB NOT NULL`, `preview_summary JSONB NULL`, `total_count BIGINT NOT NULL DEFAULT 0`, `processed_count BIGINT NOT NULL DEFAULT 0`, `failed_count BIGINT NOT NULL DEFAULT 0`, `checkpoint JSONB NULL`, `error_code VARCHAR(100) NULL`, `error_summary TEXT NULL`, requester/approver user FKs, timestamps and completion time.

Constraints: unique `(organisation_id, idempotency_key)`; tenant-scoped composite FKs for source/target schemas; valid status transitions; non-negative counters and `processed_count <= total_count` where compatible with failure/retry accounting. Preview is read-only. Apply must be approved, bounded, resumable, idempotent, audited, and avoid private document contents in error fields.

### 4.11 `metadata_projection_outbox`

Columns: `id UUID PK`, `organisation_id UUID NOT NULL`, `document_id VARCHAR(200) NOT NULL`, `metadata_revision INTEGER NOT NULL`, `event_type VARCHAR(80) NOT NULL`, `status VARCHAR(20) NOT NULL DEFAULT 'pending'`, `attempt_count INTEGER NOT NULL DEFAULT 0`, `next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `last_error_code VARCHAR(100) NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `processed_at TIMESTAMPTZ NULL`, `idempotency_key VARCHAR(200) NOT NULL`.

Constraints: unique `(organisation_id, idempotency_key)`; positive revision; non-negative attempt count; indexed pending work `(status, next_attempt_at)` and tenant/document/revision. Dispatcher must be idempotent, tenant-aware, and ignore stale/out-of-order revisions. Metadata transaction commits independently of projection success. Use a CLI dispatcher invoked by an approved scheduler; the scheduler/runtime itself is deployment configuration, not a new application dependency in this schema decision.

## 5. Typed value rules

Initial supported scalar value types: `text`, `integer`, `decimal`, `boolean`, `date`, `datetime`, and `vocabulary_term`. A structured JSON field type is not enabled by default; if required, it needs an explicit contract, schema validator, and query/index policy before implementation. Do not persist arbitrary Python objects or executable validation expressions.

For a `known` value item, exactly one typed slot is populated and must match `value_type`. For non-value states, no child items are stored. Multi-value item order is stable through `ordinal`. Single cardinality permits exactly one item. Service-level validation is mandatory; database constraints provide a second line of defense.

## 6. Cross-table constraint matrix

| Relationship | Database enforcement |
|---|---|
| Schema → organisation | FK; unique `(id, organisation_id)` |
| Field → schema/organisation | Composite FK |
| Document type → schema/organisation | Composite FK |
| Document type field → document type and field | Composite FKs; same schema and tenant |
| Vocabulary → organisation | FK; unique tenant/key |
| Vocabulary version → vocabulary | Composite FK; unique vocabulary/version |
| Term → vocabulary version | Composite FK; unique version/term key |
| Value set → schema/field/organisation | Composite FKs; same tenant and schema |
| Value item → value set | FK/composite FK; unique ordinal |
| Migration job → source/target schemas | Composite FKs; same tenant |
| Outbox → organisation | FK; tenant/revision/idempotency indexes |
| Value set → document | No DB FK in first rollout; tenant-scoped manifest ownership check in service |

## 7. Required query/index patterns

1. Tenant's current published schema lookup; partial unique index if one published schema per tenant is confirmed.
2. Schema/version field-definition lookup by `(schema_id, field_key)`.
3. Tenant/document metadata read by `(organisation_id, document_id, schema_id)`.
4. Filterable field value lookup by field definition and supported typed value column, always including tenant scope.
5. Pending outbox jobs by `(status, next_attempt_at)`; claim/lease mechanism must prevent duplicate concurrent dispatch.
6. Migration-job lookup by `(organisation_id, status, created_at)` and unique tenant/idempotency key.

Avoid indexing every metadata field automatically. Add value indexes only for declared filterable/sortable fields and measured query patterns. Index selection must be validated with `EXPLAIN` on disposable PostgreSQL using representative queries.

## 8. Transaction, concurrency, and audit invariants

- Resolve tenant from authenticated membership; never trust request `organisation_id` as authorization.
- Check active user, membership, organisation lifecycle, resource permission, and manifest ownership before metadata access.
- Validate schema/version, field, type, cardinality, state, vocabulary term status, and requiredness before write.
- Use `expected_revision` for mutable draft/value-set writes; stale revisions return conflict.
- In one transaction, write value-set/items, revision, required success audit event, and outbox row; commit once.
- Audit helper used in this transaction must add to the caller's SQLAlchemy session and must not commit independently.
- Failed-operation audit after rollback is a separate transaction and must not be presented as atomic with the failed mutation.
- Projection failure never erases committed metadata; retries/rebuilds converge idempotently and reject stale revisions.

## 9. Explicitly deferred decisions

- Relational document registry and document FK.
- Numeric precision/scale defaults and specialized structured JSON types.
- Final pagination envelope/API response shape after frontend client reconciliation.
- Detailed schema-publication approval policy beyond the accepted configurable approval baseline.
- AI-generated metadata suggestions and human acceptance workflow.
- Production worker/scheduler hosting choice; dispatcher contract is CLI-based, scheduling is deployment-specific.

## 10. G1 exit checklist

- [x] Typed relational values and explicit multi-value items accepted.
- [x] Missing/unknown/not-applicable/not-yet-reviewed semantics accepted.
- [x] Vocabulary identity and immutable version records accepted.
- [x] Normalized document-type/field associations accepted.
- [x] Document registry/FK excluded from first metadata migration.
- [x] Transaction-aware success audit accepted.
- [x] Durable outbox and CLI dispatcher accepted as the working design.
- [x] Optimistic revision checks and immutable published versions accepted.
- [ ] G0 formal sign-off recorded after required live Task 05.3 tenant-isolation/concurrency evidence.
- [ ] Physical DDL reviewed against active checkout before migration coding.

**G1 design baseline is approved; this does not waive G0 and does not authorize applying migrations to any live database.**
