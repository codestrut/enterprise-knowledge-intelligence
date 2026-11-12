# EKIP Phase 1 Backend Capability Test Suite

**Snapshot basis:** branch `feature/organisation-knowledge-management`, commit `9918263`\
**Prepared:** 2026-11-03\
**Scope:** backend tests only; no production code or database migration changed.

## Files added

- `tests/api/test_phase1_backend_capabilities.py`
- `tests/unit/test_phase1_migration_safety.py`

The API tests use a temporary SQLite identity database and the real EKIP authentication, permissions, ORM, API route table, and token/session code. Only the embedding, grounding-model, and RAG-pipeline imports are stubbed during API module loading because those model dependencies are not used by the capabilities under test. No test uses a mocked authentication service or mocked permission evaluator.

The migration safety tests inspect Migration 0007 without upgrading or downgrading any database.

## Test command

```bash
python -m pytest \
  tests/api/test_phase1_backend_capabilities.py \
  tests/unit/test_phase1_migration_safety.py \
  -q --tb=short
```

## Baseline on the supplied snapshot

**11 passed, 9 failed.** The red tests are intentional capability gates: they show where the approved Phase 1 behavior is not implemented or where Migration 0007 needs correction.

### Confirmed working in the snapshot

- `login_platform_operator()` creates a platform-only refresh session with `membership_id = NULL`.
- The refresh token is stored as a SHA-256 hash, not as plaintext.
- Platform-only refresh rotation works and preserves an empty tenant permission set.
- Platform-only principals cannot read tenant documents.
- Existing tenant administrator permissions are retained.
- Non-administrator tenant roles do not receive member-management, auth-configuration, or tenant-audit permissions.
- The real invitation/settings Pydantic contracts and SQLAlchemy model constraints validate the covered inputs.

### Current failures to resolve in Phase 1

1. `/auth/login` does not call the independent platform-operator login path; a platform-only user receives HTTP 401.
2. `/auth/me` still requires a tenant membership and cannot return a platform-only profile.
3. A suspended `TenantOnboarding` record does not invalidate an existing access token when `Organisation.is_active` remains true.
4. Password login still succeeds for a tenant whose onboarding status is `suspended` when the organisation flag remains active.
5. Refresh-token rotation still succeeds for that suspended tenant.
6. `tenant:read` is currently granted only to the organisation administrator, not all three tenant roles as specified in the Phase 1 approval.
7. Sixteen required tenant/platform administration routes are not registered (overview, members, invitations, tenant settings, suspension/reactivation, platform role listing/revocation and platform audit).
8. Migration 0007's revision ID is 36 characters. Alembic's default version table uses `version_num VARCHAR(32)`; shorten the revision identifier or configure a compatible version table before applying it.
9. Migration 0007's downgrade deletes rows from `auth_refresh_sessions` where `membership_id IS NULL`. Downgrade must not silently destroy platform-only sessions; it should refuse to proceed while such rows remain, or use a separately approved preservation strategy.

## Existing regression checks run

The following existing auth/lifecycle tests were also run against the snapshot:

```bash
python -m pytest \
  tests/unit/test_auth_service.py \
  tests/unit/test_auth_permissions.py \
  tests/unit/test_auth_models.py \
  tests/unit/test_auth_migration.py \
  tests/unit/test_task06_tenant_lifecycle.py \
  tests/unit/test_task06_tenant_onboarding_service.py \
  -q --tb=short
```

**Result: 69 passed.**

The combined command covering the new Phase 1 suite plus these existing regressions resulted in **80 passed, 9 failed**.

## Coverage still required after the corresponding services/routes exist

- Invitation creation, secure token delivery, expiry, organisation/email binding, atomic single-use acceptance and revocation.
- Tenant member list/update/deactivate/remove endpoints, including cross-tenant denial.
- Last-active-administrator protection under concurrent PostgreSQL transactions. SQLite tests are not a substitute for this concurrency test.
- Tenant settings API authorization and persistence.
- Platform suspension/reactivation, platform role revocation and audit endpoint sanitization.
- Aggregate overview calculations and the zero-knowledge platform/tenant boundary.

## Safety notes

- No database migration was executed.
- No existing project file was overwritten.
- These tests are a capability specification and current-state diagnostic. Do not interpret the expected failing tests as regressions introduced by this test bundle.
