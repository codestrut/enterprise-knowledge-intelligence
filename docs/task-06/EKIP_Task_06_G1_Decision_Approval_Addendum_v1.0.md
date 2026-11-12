# EKIP Task 06 — G1 Decision Approval Addendum

**Recorded:** 22 October 2026
**Decision:** User approved the G1 Physical Data Model Decision Proposal v1.0 as the working design baseline.

The approval covers the following recommendations:

- Typed relational metadata value items with explicit multi-value rows.
- Distinct missing, unknown, not-applicable, and not-yet-reviewed semantics.
- Separate vocabulary identity and immutable vocabulary-version records.
- Normalized document-type-to-field associations.
- No document registry or document FK in the first metadata migration.
- Transaction-aware success audit writes.
- Durable transactional projection outbox with an idempotent CLI dispatcher.
- Tenant-scoped relational constraints and optimistic revision checks.

This approval authorizes completion of the physical-schema specification and migration plan. It does **not** waive G0, authorize physical DDL/migration creation before G0 sign-off, or authorize migration against any live/production database.
