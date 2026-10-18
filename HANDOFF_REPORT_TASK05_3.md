# EKIP Task 05.3 — Refresh-Family Concurrency Fix

Date: 2026-10-18
Status: Automated auth verification PASS; deployment verification NOT VERIFIED.

## Changes
- Added PostgreSQL transaction-scoped refresh-family advisory locking.
- Applied family-lock-first ordering to refresh rotation, single-token logout,
  and whole-family logout.
- Family revocation locks refresh-session rows in ascending ID order.
- Configured the auth engine for PostgreSQL READ COMMITTED isolation.
- Configured PostgreSQL lock_timeout=5000ms and statement_timeout=15000ms.
- Added regression tests for concurrent old-token replay, replay racing a
  legitimate refresh, lock ordering, and database isolation.
- Strengthened the refresh-versus-family-logout race test to verify that a
  token returned by the competing refresh is rejected after logout completes.

## Verification Evidence
- PostgreSQL integration suite after the final assertion:
  13 passed in 25.27 seconds.
- Authentication unit suite:
  16 passed in 2.78 seconds.
- Focused strengthened logout-race test:
  1 passed in 6.94 seconds.
- Combined distinct integration and unit tests: 29 passed.
- Python compilation and pytest collection succeeded before the final assertion.
- PostgreSQL lock-order regression test passed.
- API logout route calls revoke_refresh_family(db, context.family_id).

## Scope and Limitations
- These results verify the local automated test runs only.
- Live deployment/container verification has not been performed as part of
  this Task 05.3 check.
- No Git staging or commits were performed.
- Existing project changes and backups have been preserved.

## Next Steps
1. Review all revocation paths and the final diff.
2. Run any broader backend suite required by the existing project checklist.
3. Perform the approved live verification before claiming deployment readiness.
4. Obtain explicit authorization before staging or committing changes.
