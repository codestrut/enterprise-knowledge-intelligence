# Task 05 Identity, Authentication, and Session Foundation

This increment hardens the route-independent identity and session foundation.
It does not implement HTTP authentication or claim that existing API routes
enforce tenant membership.

## Password handling

New passwords use Argon2id after validation. Policy requires at least 15 Unicode
code points, permits at most 128 code points and 512 UTF-8 bytes, and rejects
invalid Unicode without truncation or normalization. A small source-controlled
offline denylist catches several common whole-password values; it is not a
comprehensive compromised-password corpus. Runtime breach checks are not used
because they disclose password-derived information to another service and
would make account creation depend on network availability. Verification
applies the size bounds before invoking Argon2id.

## Authentication and transactions

Credential lookup uses ordinary reads. The database transaction is rolled
back before Argon2id verification. Login then opens a short transaction, locks
the user and active membership/organisation scope, rechecks account state, and
creates a membership-scoped session. PostgreSQL-specific behavior is covered
by `tests/integration/test_auth_postgres.py`; those tests require the explicit
test URL described below and are skipped when it is absent.

Multiple active memberships are returned as safe organisation options only
after password verification. A requested organisation is accepted only when
the verified user's active membership exists. The organisation selection
response does not reveal membership roles or permissions.

## Refresh sessions and retry semantics

Refresh tokens are 256-bit random values; only a SHA-256 hash is stored. Each
family has a fixed 30-day absolute expiry and a 7-day idle timeout. Rotations
lock the old session row and current user, membership, and organisation rows
for the short state-changing transaction. PostgreSQL integration tests exercise
two simultaneous refresh calls with the same retry key.

The client must persist a fresh random 256-bit rotation key before sending a
refresh request and reuse that exact key if it retries the request. The next
token is deterministically derived from the old token and this key, while only
its hash is persisted. Thus the old token by itself cannot recover the next
token. A valid retry with the same key returns the same replacement; reuse
with a different or missing key is treated as token reuse and revokes the
remaining family. This avoids a broad grace window but requires clients to
coordinate refresh retries across browser tabs. No HTTP client or endpoint is
implemented here.

## Platform and organisation permissions

Organisation memberships use the existing tenant role and permission catalog.
Platform administration is a user-level flag resolved through a separate
`PlatformPermission` catalog and grants no tenant document permission. The
security migration aborts if legacy memberships contain a platform role, so
an operator must review such records rather than silently reclassifying them.
No legacy documents or global KnowledgeBase are assigned to an organisation.

## Bootstrap and audit

The explicit CLI supports `platform-admin` and `organisation` bootstrap
commands. Both require `--confirm`; a new identity gets an interactive password
prompt twice and no default credentials. Existing identities are not reset or
promoted implicitly. Bootstrap and session lifecycle changes write metadata to
`auth_audit_events`; tokens, password material, and hashes are not placed in
audit details.

Examples (use only a separately provisioned development or test database):

```sh
EKIP_DATABASE_URL='postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database>' \
  .venv/bin/python -m src.auth.bootstrap platform-admin --email admin@example.invalid --confirm

EKIP_DATABASE_URL='postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<database>' \
  .venv/bin/python -m src.auth.bootstrap organisation --name Example --slug example \
  --admin-email admin@example.invalid --confirm
```

## Migrations and test database safety

No database URL is loaded from `.env` and importing auth models opens no
connection. Use `EKIP_DATABASE_URL` only for an explicitly reviewed migration
target. The migrations touch auth tables only; they do not inspect or change
documents, uploads, manifests, production containers, or volumes. Revision
`0003_auth_hardening` adds platform/organisation status, bounded session
lifetime metadata, membership/user consistency, and audit events. It refuses
to proceed when old membership rows use the legacy `platform_administrator`
role.

The Docker image copies `migrations/` and `alembic.ini` alongside the source.
No image was built or deployed as part of this change.

PostgreSQL integration tests require `EKIP_TEST_DATABASE_URL` pointing to a
loopback `postgresql+psycopg` database whose name includes `test`. The suite
refuses an unrelated or unknown unversioned schema and only upgrades known
EKIP migration revisions. Tests use uniquely named rows and do not drop tables,
schemas, records, containers, or volumes. The URL is never printed. If Docker
or PostgreSQL is unavailable, run the local tests and report PostgreSQL checks
as not verified; SQLite is not a substitute for PostgreSQL locking evidence.

## Protected API and tenant workspaces (Task 05.2)

The API now exposes managed `POST /auth/login`, `POST /auth/refresh`, and
authenticated `POST /auth/logout`. Login accepts an optional `organisation_id`
only to select among the authenticated user's active memberships. Every access
token is short-lived, signed with `EKIP_ACCESS_TOKEN_SECRET`, and checked
against the current active user, membership, organisation, and refresh-session
family on each protected request. It is not a bearer of stale role claims.

`GET /documents` and `/tenant/status` require `documents:read`; `POST
/documents` requires `documents:upload`; `POST /query` requires
`documents:query`; `GET /documents/{document_id}/file` requires
`documents:read`; and `DELETE /documents/{document_id}` requires
`documents:delete`. Missing or invalid bearer credentials receive 401;
authenticated callers missing the route permission receive 403. `/health`
returns only `{"status":"ok"}` and remains public. No member-management,
authentication-configuration, or audit HTTP routes currently exist; their
permissions remain defined for future routes and do not create endpoints here.

The Vite client keeps access tokens in memory, attaches them to API requests,
prompts for managed sign-in after 401/session expiry, and hides upload/delete
controls when the current membership lacks those permissions. Refresh tokens
are not persisted or automatically rotated by this UI, so a page reload requires
sign-in again.

New document records use `EKIP_TENANT_DATA_DIRECTORY` (default
`data/tenants/<organisation UUID>/`) with one manifest, upload directory,
knowledge base, and retrieval pipeline per organisation. The same loaded
embedding model instance is reused; document chunks and retrieval indexes are
not shared between tenants. Startup restores only UUID-named tenant folders.
The legacy global `data/uploads` and `data/documents_manifest.json` are left
untouched and ignored. They are quarantined; there is no automatic assignment
or migration into any organisation. A future operator migration must explicitly
map and review each legacy document before copying it into a tenant workspace.

Configure the backend with an explicit PostgreSQL URL and an independent
random signing secret of at least 32 bytes. Use private environment injection,
not source control or reports. The local configuration keys are
`EKIP_DATABASE_URL`, `EKIP_ACCESS_TOKEN_SECRET`, and optionally
`EKIP_TENANT_DATA_DIRECTORY`; their values belong in a local secret manager or
untracked environment file. No production URL or key is included in this
repository.

## Remaining API gates

The API/tenant boundary is exercised with model-free isolated FastAPI tests,
and the auth database path is separately exercised against isolated PostgreSQL.
The Playwright smoke test still targets the previously running Task 04 test API
on port 8001, which was not rebuilt or replaced during this increment. It
therefore verifies loopback proxy and visible UI behavior, not the new auth
routes running in a container. Cookie/CSRF-based browser sessions, automatic
refresh coordination across tabs, rate limiting, member-management routes,
platform administration endpoints, and explicit legacy-document migration
remain future gates.
