"""PostgreSQL-only auth verification for an explicitly isolated test database.

Set EKIP_TEST_DATABASE_URL to a loopback PostgreSQL database whose name
contains "test". The fixture refuses remote hosts and unrelated schemas, only
upgrades the known EKIP auth migration chain, and leaves uniquely named test
records in place rather than issuing destructive cleanup statements.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import UTC, datetime
import hashlib
import os
import secrets
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url

from src.auth.models import (
    AuditEvent,
    Organisation,
    OrganisationMembership,
    RefreshSessionRecord,
    User,
)
from src.auth.passwords import hash_password
from src.auth.permissions import Role
from src.auth.service import (
    AuthenticationError,
    authenticate_managed_user,
    login_managed_user,
    rotate_refresh_session,
    revoke_refresh_family,
    revoke_refresh_session,
)


_RAW_URL = os.environ.get("EKIP_TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("EKIP_TEST_DATABASE_URL is not configured", allow_module_level=True)

_URL = make_url(_RAW_URL)
if _URL.drivername != "postgresql+psycopg":
    pytest.skip("EKIP_TEST_DATABASE_URL must use postgresql+psycopg", allow_module_level=True)
if _URL.host not in {"127.0.0.1", "localhost", "::1"}:
    pytest.skip("PostgreSQL integration tests require a loopback host", allow_module_level=True)
if not _URL.database or "test" not in _URL.database.lower():
    pytest.skip("PostgreSQL database name must contain 'test'", allow_module_level=True)


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(_URL, pool_pre_ping=True, pool_size=5, max_overflow=5)
    try:
        with engine.connect() as connection:
            db_name = connection.scalar(text("SELECT current_database()"))
            if db_name != _URL.database:
                pytest.fail("Connected PostgreSQL database does not match the configured test name")
            existing_tables = set(inspect(connection).get_table_names())
            if "alembic_version" not in existing_tables and existing_tables:
                pytest.fail("Refusing to migrate a non-empty unversioned test database")
            if "alembic_version" in existing_tables:
                current = connection.scalar(text("SELECT version_num FROM alembic_version"))
                if current not in {
                    "0001_identity_foundation",
                    "0002_auth_refresh_sessions",
                    "0003_auth_hardening",
                    "0004_scoped_security_audit",
                }:
                    pytest.fail("Refusing to change an unknown Alembic revision")

        config = Config("alembic.ini")
        previous_auth_url = os.environ.get("EKIP_DATABASE_URL")
        os.environ["EKIP_DATABASE_URL"] = _RAW_URL
        try:
            command.upgrade(config, "head")
        finally:
            if previous_auth_url is None:
                os.environ.pop("EKIP_DATABASE_URL", None)
            else:
                os.environ["EKIP_DATABASE_URL"] = previous_auth_url
        yield engine
    finally:
        engine.dispose()


def _new_identity(engine):
    suffix = uuid4().hex
    user = User(
        email=f"pg-{suffix}@example.invalid",
        password_hash=hash_password("violet-cactus-orbit-sailed"),
    )
    organisation = Organisation(name=f"PG test {suffix}", slug=f"pg-test-{suffix}")
    membership = OrganisationMembership(
        user=user, organisation=organisation, role=Role.READER
    )
    with Session(engine) as db:
        db.add_all([user, organisation, membership])
        db.commit()
        db.refresh(user)
        db.refresh(organisation)
        db.refresh(membership)
        return user.id, user.email, organisation.id, membership.id


def test_postgres_auth_schema_constraints_and_new_engine_persistence(pg_engine):
    user_id, email, _org_id, membership_id = _new_identity(pg_engine)
    duplicate_email = User(email=email, password_hash=hash_password("violet-cactus-orbit-sailed"))
    with Session(pg_engine) as db:
        db.add(duplicate_email)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

    with Session(pg_engine) as db:
        grant = login_managed_user(db, email, "violet-cactus-orbit-sailed")
    pg_engine.dispose()
    reopened = create_engine(_URL, pool_pre_ping=True)
    try:
        with Session(reopened) as db:
            session_record = db.scalar(
                select(RefreshSessionRecord).where(
                    RefreshSessionRecord.token_hash
                    == hashlib.sha256(grant.refresh_token.encode()).hexdigest()
                )
            )
            assert session_record is not None
            assert session_record.user_id == user_id
            assert session_record.membership_id == membership_id
            assert db.scalar(select(AuditEvent).where(AuditEvent.actor_user_id == user_id))
    finally:
        reopened.dispose()


def test_postgres_rejects_refresh_session_user_membership_mismatch(pg_engine):
    _user_id, email, _org_id, membership_id = _new_identity(pg_engine)
    other_user = User(
        email=f"other-{uuid4().hex}@example.invalid",
        password_hash=hash_password("violet-cactus-orbit-sailed"),
    )
    with Session(pg_engine) as db:
        db.add(other_user)
        db.flush()
        bad = RefreshSessionRecord(
            user_id=other_user.id,
            membership_id=membership_id,
            token_hash=secrets.token_hex(32),
            family_id=uuid4(),
            expires_at=datetime.now(UTC),
            family_expires_at=datetime.now(UTC),
            last_used_at=datetime.now(UTC),
        )
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_postgres_credential_verification_does_not_issue_for_update(pg_engine):
    _user_id, email, _org_id, _membership_id = _new_identity(pg_engine)
    seen_sql: list[str] = []

    def collect(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "users" in statement.lower():
            seen_sql.append(statement.lower())

    event.listen(pg_engine, "before_cursor_execute", collect)
    try:
        with Session(pg_engine) as db:
            authenticate_managed_user(db, email, "violet-cactus-orbit-sailed")
    finally:
        event.remove(pg_engine, "before_cursor_execute", collect)
    assert seen_sql
    assert all("for update" not in statement for statement in seen_sql)


def test_postgres_password_verification_runs_without_a_held_user_lock(pg_engine, monkeypatch):
    _user_id, email, _org_id, _membership_id = _new_identity(pg_engine)
    import src.auth.service as auth_service

    original_verify = auth_service.verify_password
    acquired_during_verify = False

    def check_lock_released(password, encoded_hash):
        nonlocal acquired_during_verify
        with Session(pg_engine) as contender:
            contender.scalar(
                select(User.id)
                .where(User.email == email)
                .with_for_update(nowait=True)
            )
            contender.rollback()
            acquired_during_verify = True
        return original_verify(password, encoded_hash)

    monkeypatch.setattr(auth_service, "verify_password", check_lock_released)
    with Session(pg_engine) as db:
        grant = login_managed_user(db, email, "violet-cactus-orbit-sailed")
    assert grant.principal.user_id == _user_id
    assert acquired_during_verify


def test_postgres_concurrent_authentication_completes(pg_engine):
    _user_id, email, _org_id, _membership_id = _new_identity(pg_engine)

    def authenticate():
        with Session(pg_engine) as db:
            return authenticate_managed_user(db, email, "violet-cactus-orbit-sailed")

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _i: authenticate(), range(2)))
    assert first == second


def test_postgres_concurrent_refresh_retry_with_same_key_is_idempotent(pg_engine):
    _user_id, email, _org_id, _membership_id = _new_identity(pg_engine)
    with Session(pg_engine) as db:
        original = login_managed_user(db, email, "violet-cactus-orbit-sailed")
    retry_key = secrets.token_urlsafe(32)

    def rotate():
        with Session(pg_engine) as db:
            return rotate_refresh_session(db, original.refresh_token, retry_key)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _i: rotate(), range(2)))
    assert first.refresh_token == second.refresh_token
    assert first.expires_at == second.expires_at


def test_postgres_concurrent_different_key_replay_revokes_family_without_deadlock(pg_engine):
    """Concurrent reuse of one old token with different keys must revoke its family."""
    repetitions = 50

    for _ in range(repetitions):
        user_id, email, _org_id, _membership_id = _new_identity(pg_engine)
        with Session(pg_engine) as db:
            original = login_managed_user(db, email, "violet-cactus-orbit-sailed")

        start = Barrier(2)

        def rotate(rotation_key):
            with Session(pg_engine) as db:
                # Bound lock waits so a regression fails promptly instead of hanging.
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                start.wait(timeout=5)
                try:
                    grant = rotate_refresh_session(
                        db, original.refresh_token, rotation_key
                    )
                    return ("success", grant)
                except AuthenticationError:
                    return ("rejected", None)

        rotation_keys = [secrets.token_urlsafe(32), secrets.token_urlsafe(32)]
        assert rotation_keys[0] != rotation_keys[1]

        # Unexpected database exceptions (including PostgreSQL deadlock/lock-timeout
        # errors) deliberately propagate and fail the test.
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(rotate, rotation_keys))

        assert sorted(outcome for outcome, _grant in outcomes) == ["rejected", "success"]

        with Session(pg_engine) as db:
            records = list(
                db.scalars(
                    select(RefreshSessionRecord).where(
                        RefreshSessionRecord.family_id == original.family_id
                    )
                )
            )
            assert len(records) == 2
            assert all(record.revoked_at is not None for record in records)
            assert db.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.actor_user_id == user_id,
                    AuditEvent.event_type == "auth.session_reuse_detected",
                )
            ) is not None

@pytest.fixture
def pg_engine_bounded(pg_engine):
    """Create test connections with connection-level PostgreSQL timeouts."""
    engine = create_engine(
        pg_engine.url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        connect_args={"options": "-c lock_timeout=5000 -c statement_timeout=20000"},
    )
    try:
        yield engine
    finally:
        engine.dispose()


def test_postgres_refresh_after_family_logout_is_rejected(pg_engine_bounded):
    """A refresh arriving after family logout must not create a usable token."""
    _user_id, email, _org_id, _membership_id = _new_identity(pg_engine_bounded)
    with Session(pg_engine_bounded) as db:
        original = login_managed_user(db, email, "violet-cactus-orbit-sailed")

    with Session(pg_engine_bounded) as db:
        revoke_refresh_family(db, original.family_id)

    with Session(pg_engine_bounded) as db, pytest.raises(AuthenticationError):
        rotate_refresh_session(db, original.refresh_token, secrets.token_urlsafe(32))

    with Session(pg_engine_bounded) as db:
        records = list(
            db.scalars(
                select(RefreshSessionRecord).where(
                    RefreshSessionRecord.family_id == original.family_id
                )
            )
        )
        assert records
        assert all(record.revoked_at is not None for record in records)


def test_postgres_refresh_racing_family_logout_leaves_no_active_tokens(
    pg_engine_bounded,
):
    """Refresh and family logout racing must leave the entire family revoked."""
    engine = pg_engine_bounded
    repetitions = 50

    for _ in range(repetitions):
        _user_id, email, _org_id, _membership_id = _new_identity(engine)
        with Session(engine) as db:
            original = login_managed_user(db, email, "violet-cactus-orbit-sailed")

        start = Barrier(2)

        def refresh():
            with Session(engine) as db:
                start.wait(timeout=5)
                try:
                    grant = rotate_refresh_session(
                        db, original.refresh_token, secrets.token_urlsafe(32)
                    )
                    return ("refreshed", grant)
                except AuthenticationError:
                    return ("rejected", None)

        def logout_family():
            with Session(engine) as db:
                start.wait(timeout=5)
                revoke_refresh_family(db, original.family_id)
                return "logged_out"

        with ThreadPoolExecutor(max_workers=2) as pool:
            refresh_future = pool.submit(refresh)
            logout_future = pool.submit(logout_family)
            refresh_outcome = refresh_future.result(timeout=30)
            assert logout_future.result(timeout=30) == "logged_out"

        # Whichever operation wins, no token in this family may remain active.
        with Session(engine) as db:
            records = list(
                db.scalars(
                    select(RefreshSessionRecord).where(
                        RefreshSessionRecord.family_id == original.family_id
                    )
                )
            )
            assert records
            assert all(record.revoked_at is not None for record in records)

        if refresh_outcome[0] == "refreshed":
            with Session(engine) as db, pytest.raises(AuthenticationError):
                rotate_refresh_session(
                    db,
                    refresh_outcome[1].refresh_token,
                    secrets.token_urlsafe(32),
                )

# EKIP Task 05.3: refresh-family lock regression tests
#
# Append to tests/integration/test_auth_postgres.py, after the existing
# pg_engine_bounded fixture. Add `revoke_refresh_session` to the existing
# `from src.auth.service import (...)` block. Everything else used here is
# already imported in that file.
#
# Before the family lock patch, the two race tests fail. On a scratch
# PostgreSQL 16, the two-old-tokens case deadlocked (40P01) in 45 of 50
# repetitions, and the stolen-token case left a live token in 48 of 50.
# After the patch, both pass.
#
# Also strengthen the existing
# test_postgres_refresh_racing_family_logout_leaves_no_active_tokens by adding,
# after its final records check (inside the loop):
#
#        if refresh_outcome[0] == "refreshed":
#            with Session(engine) as db, pytest.raises(AuthenticationError):
#                rotate_refresh_session(
#                    db, refresh_outcome[1].refresh_token, secrets.token_urlsafe(32)
#                )

_FAMILY_RACE_REPETITIONS = 50
_RACE_PASSWORD = "violet-cactus-orbit-sailed"


def _race_rotations(engine, attempts):
    """Run rotate_refresh_session for each (token, key) at the same moment.

    PostgreSQL errors (deadlock, lock or statement timeout) propagate and fail the test.
    """
    start = Barrier(len(attempts))

    def attempt(token_and_key):
        token, key = token_and_key
        with Session(engine) as db:
            start.wait(timeout=5)
            try:
                return ("success", rotate_refresh_session(db, token, key))
            except AuthenticationError:
                return ("rejected", None)

    with ThreadPoolExecutor(max_workers=len(attempts)) as pool:
        return [f.result(timeout=30) for f in [pool.submit(attempt, a) for a in attempts]]


def _assert_family_fully_revoked(engine, family_id):
    with Session(engine) as db:
        records = list(
            db.scalars(
                select(RefreshSessionRecord).where(RefreshSessionRecord.family_id == family_id)
            )
        )
    assert records
    assert all(record.revoked_at is not None for record in records)


def _assert_refresh_token_dead(engine, refresh_token):
    with Session(engine) as db, pytest.raises(AuthenticationError):
        rotate_refresh_session(db, refresh_token, secrets.token_urlsafe(32))


def test_postgres_auth_database_uses_read_committed(pg_engine_bounded):
    """The family lock relies on each statement seeing rows committed before it."""
    with Session(pg_engine_bounded) as db:
        assert db.scalar(text("SHOW transaction_isolation")) == "read committed"


def test_postgres_concurrent_replay_of_two_old_tokens_revokes_family_without_deadlock(
    pg_engine_bounded,
):
    """Audit case: two different old tokens from one family replayed at once."""
    engine = pg_engine_bounded
    for _ in range(_FAMILY_RACE_REPETITIONS):
        _user_id, email, _org_id, _membership_id = _new_identity(engine)
        with Session(engine) as db:
            t0 = login_managed_user(db, email, _RACE_PASSWORD)
        with Session(engine) as db:
            t1 = rotate_refresh_session(db, t0.refresh_token, secrets.token_urlsafe(32))
        with Session(engine) as db:
            t2 = rotate_refresh_session(db, t1.refresh_token, secrets.token_urlsafe(32))

        outcomes = _race_rotations(
            engine,
            [
                (t0.refresh_token, secrets.token_urlsafe(32)),
                (t1.refresh_token, secrets.token_urlsafe(32)),
            ],
        )

        assert [outcome for outcome, _grant in outcomes] == ["rejected", "rejected"]
        _assert_refresh_token_dead(engine, t2.refresh_token)
        _assert_family_fully_revoked(engine, t0.family_id)


def test_postgres_old_token_replay_racing_legitimate_refresh_leaves_family_dead(
    pg_engine_bounded,
):
    """A stolen old token replayed while the real user refreshes: either order ends dead."""
    engine = pg_engine_bounded
    for _ in range(_FAMILY_RACE_REPETITIONS):
        user_id, email, _org_id, _membership_id = _new_identity(engine)
        with Session(engine) as db:
            t0 = login_managed_user(db, email, _RACE_PASSWORD)
        with Session(engine) as db:
            t1 = rotate_refresh_session(db, t0.refresh_token, secrets.token_urlsafe(32))

        replay, legit = _race_rotations(
            engine,
            [
                (t0.refresh_token, secrets.token_urlsafe(32)),
                (t1.refresh_token, secrets.token_urlsafe(32)),
            ],
        )

        assert replay[0] == "rejected"
        if legit[0] == "success":
            _assert_refresh_token_dead(engine, legit[1].refresh_token)
        _assert_family_fully_revoked(engine, t0.family_id)
        with Session(engine) as db:
            assert db.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.actor_user_id == user_id,
                    AuditEvent.event_type == "auth.session_reuse_detected",
                )
            ) is not None


def test_postgres_family_lock_is_taken_before_any_row_lock(pg_engine_bounded):
    """Refresh, single-token logout and family logout must take the family lock first."""
    engine = pg_engine_bounded
    _user_id, email, _org_id, _membership_id = _new_identity(engine)
    with Session(engine) as db:
        original = login_managed_user(db, email, _RACE_PASSWORD)

    trace: list[str] = []

    def collect(_conn, _cursor, statement, _parameters, _context, _executemany):
        lowered = statement.lower()
        if "pg_advisory_xact_lock" in lowered:
            trace.append("family_lock")
        elif "for update" in lowered:
            trace.append("row_lock")

    def first_lock(operation) -> str:
        trace.clear()
        event.listen(engine, "before_cursor_execute", collect)
        try:
            operation()
        finally:
            event.remove(engine, "before_cursor_execute", collect)
        assert trace, "operation took no locks"
        return trace[0]

    def refresh():
        with Session(engine) as db:
            return rotate_refresh_session(db, original.refresh_token, secrets.token_urlsafe(32))

    grant_holder = {}

    def refresh_and_keep():
        grant_holder["grant"] = refresh()

    assert first_lock(refresh_and_keep) == "family_lock"

    def single_logout():
        with Session(engine) as db:
            revoke_refresh_session(db, grant_holder["grant"].refresh_token)

    assert first_lock(single_logout) == "family_lock"

    def family_logout():
        with Session(engine) as db:
            revoke_refresh_family(db, original.family_id)

    assert first_lock(family_logout) == "family_lock"
