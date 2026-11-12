# Task 06 Implementation Checklist — Role-Based Onboarding and Recovery

**Updated:** 2026-10-22
**Scope:** first persisted tenant-onboarding slice; additive changes only.

## Decisions recorded
- [x] G0 sign-off explicitly approved by project owner; local isolated PostgreSQL is the designated environment (no university deployment required).
- [x] Creator and approver may be the same user when that user's platform role assignments grant both permissions.
- [x] Platform roles are separate from organisation membership roles.
- [x] Provisioning recovery uses a durable start timestamp, row lock, stale threshold, audit event, and a separate retry action.
- [x] Provisioning retries are bounded to five attempts before operator review.

## Implementation inventory
- [x] Add platform permission values and built-in role profiles.
- [x] Add persisted `platform_role_assignments` model and additive Alembic revision `0006_platform_roles_and_recovery`.
- [x] Add role-grant endpoint guarded by platform role-assignment permission.
- [x] Guard tenant creation, approval, retry and recovery with distinct permissions; legacy platform-admin flag remains a compatibility super-admin grant.
- [x] Add `provisioning_started_at`, stale recovery service and recovery endpoint.
- [x] Audit same-actor approval as `creator_also_approver`, not as an exception.
- [x] Focused sandbox unit tests: 68 passed in 5.15s (2026-10-22).
- [x] Offline SQL generation through `0006_platform_roles_and_recovery` succeeded in sandbox; generated SQL includes role table, constraints, and recovery timestamp.
- [ ] Run upgrade/constraint/concurrency tests against disposable PostgreSQL only.
- [ ] Confirm retry/idempotency and stale-recovery race behavior on PostgreSQL.
- [ ] Update this checklist with actual results and remaining risks after tests.

## Safety gates
- Do not run migrations against production or `ekip_task05_runa`.
- Do not claim PostgreSQL proof from SQLite/unit tests or offline SQL generation.
- Preserve uncommitted frontend, Task 05.3, and other user work.
