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
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url

from src.auth.models import (
    AuditEvent,
    Organisation,
    OrganisationMembership,
    PlatformRoleAssignment,
    RefreshSessionRecord,
    User,
)
from src.auth.passwords import hash_password
from src.auth.permissions import PlatformRole, Role
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
                known_revisions = {
                    script.revision
                    for script in ScriptDirectory.from_config(Config("alembic.ini")).walk_revisions()
                }
                if current not in known_revisions:
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


def test_postgres_tenant_session_operations_use_consistent_lock_order(pg_engine_bounded):
    """Tenant refresh and logout lock organisation, family, then session rows."""
    engine = pg_engine_bounded
    _user_id, email, _org_id, _membership_id = _new_identity(engine)
    with Session(engine) as db:
        original = login_managed_user(db, email, _RACE_PASSWORD)

    trace: list[str] = []

    def collect(_conn, _cursor, statement, _parameters, _context, _executemany):
        lowered = statement.lower()
        if "pg_advisory_xact_lock" in lowered:
            trace.append("family_lock")
        elif "for update" in lowered and "organisations" in lowered:
            trace.append("organisation_lock")
        elif "for update" in lowered:
            trace.append("row_lock")

    def lock_sequence(operation) -> list[str]:
        trace.clear()
        event.listen(engine, "before_cursor_execute", collect)
        try:
            operation()
        finally:
            event.remove(engine, "before_cursor_execute", collect)
        assert trace, "operation took no locks"
        return list(trace)

    def refresh():
        with Session(engine) as db:
            return rotate_refresh_session(db, original.refresh_token, secrets.token_urlsafe(32))

    grant_holder = {}

    def refresh_and_keep():
        grant_holder["grant"] = refresh()

    assert lock_sequence(refresh_and_keep)[:3] == [
        "organisation_lock",
        "family_lock",
        "row_lock",
    ]

    def single_logout():
        with Session(engine) as db:
            revoke_refresh_session(db, grant_holder["grant"].refresh_token)

    assert lock_sequence(single_logout)[:3] == [
        "organisation_lock",
        "family_lock",
        "row_lock",
    ]

    def family_logout():
        with Session(engine) as db:
            revoke_refresh_family(db, original.family_id)

    assert lock_sequence(family_logout)[:3] == [
        "organisation_lock",
        "family_lock",
        "row_lock",
    ]


class _PostgresTenantIsolationKnowledgeBase:
    """Small deterministic document store for real API authorization tests."""

    def __init__(self, embedder=None, reranker=None):
        self.embedder = embedder
        self.reranker = reranker
        self.tenant_id = None
        self.documents = {}
        self.chunks = []

    def list_documents(self):
        return list(self.documents.values())

    def delete_document(self, document_id):
        return self.documents.pop(document_id)


class _PostgresTenantIsolationPipeline:
    """Expose only the chunks in the authenticated tenant's workspace.

    The real retrieval/ranking path is covered by
    test_authenticated_query_uses_only_the_current_tenant_workspace. This
    deterministic adapter isolates the PostgreSQL-backed auth-to-workspace
    boundary without loading a model or calling an external LLM.
    """

    def __init__(self, knowledge_base, **_kwargs):
        self.knowledge_base = knowledge_base
        self.tenant_id = knowledge_base.tenant_id
        self.received_tenant_ids = []

    def query(self, question, top_k=5, tenant_id=None):
        self.received_tenant_ids.append(str(tenant_id))
        if str(tenant_id) != str(self.tenant_id):
            raise ValueError("Tenant context does not match the workspace.")
        sources = self.knowledge_base.chunks[:top_k]
        return {
            "question": question,
            "answer": "Synthetic tenant-scoped answer. [Source 1]",
            "sources": sources,
            "source_map": {},
            "citations": [],
            "invalid_citations": [],
            "grounding": [],
            "evidence": {"sufficient": bool(sources), "reason": "synthetic_test"},
            "refused": not bool(sources),
        }


def _create_admin_identity(engine, label: str):
    suffix = uuid4().hex
    user = User(
        email=f"{label}-{suffix}@example.invalid",
        password_hash=hash_password("violet-cactus-orbit-sailed"),
    )
    organisation = Organisation(
        name=f"API isolation {label} {suffix}",
        slug=f"api-isolation-{label}-{suffix}",
    )
    membership = OrganisationMembership(
        user=user,
        organisation=organisation,
        role=Role.ORGANISATION_ADMINISTRATOR,
    )
    with Session(engine) as db:
        db.add_all([user, organisation, membership])
        db.commit()
        db.refresh(user)
        db.refresh(organisation)
        return user.id, user.email, organisation.id


@pytest.fixture

def postgres_api_tenant_world(pg_engine, monkeypatch, tmp_path):
    """Use persisted PostgreSQL identities with the real authenticated document API."""
    from fastapi.testclient import TestClient

    from src.api.document_records import manifest_record
    from src.api.tenant_storage import TenantWorkspaceRegistry

    # The API's HMAC signing key is test-only and is never printed.
    monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", "test-only-key-" + secrets.token_hex(32))

    # Avoid loading the embedding model merely to import the API for these tests.
    try:
        import src.knowledge_base as knowledge_base_module
        if hasattr(knowledge_base_module, "Embedder"):
            monkeypatch.setattr(knowledge_base_module, "Embedder", lambda: object())
        from src.api import main as api_main
    except ImportError as exc:
        if exc.name == "sentence_transformers":
            pytest.skip("sentence_transformers is unavailable in this test environment")
        raise

    registry = TenantWorkspaceRegistry(
        tmp_path / "postgres-api-tenant-workspaces",
        shared_embedder=object(),
        shared_reranker=object(),
        pipeline_dependencies={},
        knowledge_base_factory=_PostgresTenantIsolationKnowledgeBase,
        pipeline_factory=_PostgresTenantIsolationPipeline,
    )
    monkeypatch.setattr(api_main, "tenant_workspaces", registry)

    def override_auth_db():
        with Session(pg_engine) as db:
            yield db

    monkeypatch.setitem(
        api_main.app.dependency_overrides, api_main.get_auth_db, override_auth_db
    )

    client = TestClient(api_main.app)
    identities = {}
    for label in ("alpha", "beta"):
        user_id, email, organisation_id = _create_admin_identity(pg_engine, label)
        response = client.post(
            "/auth/login",
            json={"email": email, "password": "violet-cactus-orbit-sailed"},
        )
        assert response.status_code == 200, response.text
        token = response.json()["access_token"]
        document_id = str(uuid4())
        workspace = registry.workspace_for(organisation_id)
        record = {
            "document_id": document_id,
            "filename": f"{label}-confidential.pdf",
            "status": "indexed",
            "chunk_count": 1,
            "sha256": secrets.token_hex(32),
        }
        workspace.knowledge_base.documents[document_id] = record
        workspace.write_manifest({document_id: manifest_record(document_id, record)})
        (workspace.upload_directory / f"{document_id}.pdf").write_bytes(
            b"%PDF-1.4\n% synthetic tenant-isolation test document\n"
        )
        identities[label] = {
            "user_id": user_id,
            "email": email,
            "organisation_id": organisation_id,
            "document_id": document_id,
            "workspace": workspace,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    try:
        yield {"client": client, "identities": identities, "registry": registry}
    finally:
        # Do not leave test-specific dependency overrides on the process-global app.
        api_main.app.dependency_overrides.pop(api_main.get_auth_db, None)


def test_postgres_authenticated_document_listing_is_tenant_scoped(postgres_api_tenant_world):
    world = postgres_api_tenant_world
    client = world["client"]
    alpha = world["identities"]["alpha"]
    beta = world["identities"]["beta"]

    alpha_response = client.get("/documents", headers=alpha["headers"])
    beta_response = client.get("/documents", headers=beta["headers"])

    assert alpha_response.status_code == 200, alpha_response.text
    assert beta_response.status_code == 200, beta_response.text
    alpha_ids = {item["document_id"] for item in alpha_response.json()["documents"]}
    beta_ids = {item["document_id"] for item in beta_response.json()["documents"]}
    assert alpha_ids == {alpha["document_id"]}
    assert beta_ids == {beta["document_id"]}
    assert beta["document_id"] not in alpha_ids
    assert alpha["document_id"] not in beta_ids


def test_postgres_authenticated_document_download_and_delete_cannot_cross_tenants(
    postgres_api_tenant_world,
):
    world = postgres_api_tenant_world
    client = world["client"]
    alpha = world["identities"]["alpha"]
    beta = world["identities"]["beta"]

    own_download = client.get(
        f"/documents/{alpha['document_id']}/file", headers=alpha["headers"]
    )
    cross_download = client.get(
        f"/documents/{beta['document_id']}/file", headers=alpha["headers"]
    )
    cross_delete = client.delete(
        f"/documents/{beta['document_id']}", headers=alpha["headers"]
    )

    assert own_download.status_code == 200
    assert own_download.content.startswith(b"%PDF-")
    assert cross_download.status_code == 404
    assert cross_delete.status_code == 404

    beta_file = beta["workspace"].upload_directory / f"{beta['document_id']}.pdf"
    assert beta["document_id"] in beta["workspace"].knowledge_base.documents
    assert beta_file.is_file(), "Cross-tenant delete must not remove the other tenant's file"
    assert beta["document_id"] in beta["workspace"].read_manifest()


def test_postgres_document_delete_audit_uses_authenticated_organisation(
    postgres_api_tenant_world, pg_engine
):
    from sqlalchemy import select

    world = postgres_api_tenant_world
    client = world["client"]
    alpha = world["identities"]["alpha"]

    response = client.delete(
        f"/documents/{alpha['document_id']}", headers=alpha["headers"]
    )
    assert response.status_code == 200, response.text

    with Session(pg_engine) as db:
        event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "document.delete",
                AuditEvent.target_id == alpha["document_id"],
            )
        )
    assert event is not None
    assert event.organisation_id == alpha["organisation_id"]
    assert event.actor_user_id == alpha["user_id"]


def test_postgres_authenticated_query_uses_only_current_tenant_workspace(
    postgres_api_tenant_world, pg_engine
):
    """Persisted PostgreSQL identities must route queries to their own workspace."""
    world = postgres_api_tenant_world
    client = world["client"]
    alpha = world["identities"]["alpha"]
    beta = world["identities"]["beta"]

    alpha_chunk = {
        "text": "alpha canary confidential project",
        "metadata": {
            "document_id": alpha["document_id"],
            "organisation_id": str(alpha["organisation_id"]),
            "source": "alpha-confidential.pdf",
            "page": 1,
        },
    }
    beta_chunk = {
        "text": "beta canary confidential project",
        "metadata": {
            "document_id": beta["document_id"],
            "organisation_id": str(beta["organisation_id"]),
            "source": "beta-confidential.pdf",
            "page": 1,
        },
    }
    alpha["workspace"].knowledge_base.chunks = [alpha_chunk]
    beta["workspace"].knowledge_base.chunks = [beta_chunk]

    alpha_response = client.post(
        "/query",
        headers=alpha["headers"],
        json={"question": "beta canary confidential project", "top_k": 5},
    )
    beta_response = client.post(
        "/query",
        headers=beta["headers"],
        json={"question": "alpha canary confidential project", "top_k": 5},
    )

    assert alpha_response.status_code == 200, alpha_response.text
    assert beta_response.status_code == 200, beta_response.text
    alpha_sources = alpha_response.json()["sources"]
    beta_sources = beta_response.json()["sources"]
    assert {item["metadata"]["document_id"] for item in alpha_sources} == {
        alpha["document_id"]
    }
    assert {item["metadata"]["document_id"] for item in beta_sources} == {
        beta["document_id"]
    }
    assert beta["document_id"] not in {
        item["metadata"]["document_id"] for item in alpha_sources
    }
    assert alpha["document_id"] not in {
        item["metadata"]["document_id"] for item in beta_sources
    }

    alpha_pipeline = alpha["workspace"].get_pipeline()
    beta_pipeline = beta["workspace"].get_pipeline()
    assert alpha_pipeline.received_tenant_ids == [str(alpha["organisation_id"])]
    assert beta_pipeline.received_tenant_ids == [str(beta["organisation_id"])]

    with Session(pg_engine) as db:
        audit_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.event_type == "knowledge.query",
                AuditEvent.actor_user_id.in_([alpha["user_id"], beta["user_id"]]),
            )
        ).all()
    events_by_actor = {event.actor_user_id: event for event in audit_events}
    assert events_by_actor[alpha["user_id"]].organisation_id == alpha["organisation_id"]
    assert events_by_actor[beta["user_id"]].organisation_id == beta["organisation_id"]

def test_postgres_audit_reads_are_scoped_to_authenticated_organisation(
    postgres_api_tenant_world,
):
    """Audit reads for persisted PostgreSQL identities must never cross tenants."""
    world = postgres_api_tenant_world
    client = world["client"]
    alpha = world["identities"]["alpha"]
    beta = world["identities"]["beta"]

    for identity in (alpha, beta):
        response = client.post(
            "/query",
            headers=identity["headers"],
            json={"question": "tenant scoped audit probe", "top_k": 5},
        )
        assert response.status_code == 200, response.text

    alpha_audit = client.get("/audit/events", headers=alpha["headers"])
    beta_audit = client.get("/audit/events", headers=beta["headers"])
    assert alpha_audit.status_code == 200, alpha_audit.text
    assert beta_audit.status_code == 200, beta_audit.text

    alpha_events = alpha_audit.json()["events"]
    beta_events = beta_audit.json()["events"]
    assert alpha_events and beta_events
    assert all(event["organisation_id"] == str(alpha["organisation_id"]) for event in alpha_events)
    assert all(event["organisation_id"] == str(beta["organisation_id"]) for event in beta_events)
    assert all(event["actor_user_id"] == str(alpha["user_id"]) for event in alpha_events)
    assert all(event["actor_user_id"] == str(beta["user_id"]) for event in beta_events)
    assert beta["document_id"] not in str(alpha_events)
    assert alpha["document_id"] not in str(beta_events)


def test_postgres_platform_admin_flag_does_not_grant_cross_tenant_content_access(
    postgres_api_tenant_world, pg_engine, request
):
    """Platform flag cannot widen a reader membership into customer-content access."""
    world = postgres_api_tenant_world
    client = world["client"]
    alpha = world["identities"]["alpha"]
    beta = world["identities"]["beta"]

    test_admin_ids = []

    def restore_test_admin_flags():
        with Session(pg_engine) as cleanup_db:
            for test_user_id in test_admin_ids:
                test_user = cleanup_db.get(User, test_user_id)
                if test_user is not None:
                    test_user.is_platform_admin = False
            cleanup_db.commit()

    request.addfinalizer(restore_test_admin_flags)

    user = User(
        email=f"platform-reader-{uuid4().hex}@example.invalid",
        password_hash=hash_password("violet-cactus-orbit-sailed"),
        is_platform_admin=True,
    )
    membership = OrganisationMembership(
        user=user,
        organisation_id=alpha["organisation_id"],
        role=Role.READER,
    )
    platform_email = user.email
    with Session(pg_engine) as db:
        db.add_all([user, membership])
        db.commit()
        db.refresh(user)
    test_admin_ids.append(user.id)

    login = client.post(
        "/auth/login",
        json={"email": platform_email, "password": "violet-cactus-orbit-sailed"},
    )
    assert login.status_code == 200, login.text
    platform_reader_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    own_list = client.get("/documents", headers=platform_reader_headers)
    cross_download = client.get(
        f"/documents/{beta['document_id']}/file", headers=platform_reader_headers
    )
    audit_read = client.get("/audit/events", headers=platform_reader_headers)
    assert own_list.status_code == 200, own_list.text
    assert {item["document_id"] for item in own_list.json()["documents"]} == {
        alpha["document_id"]
    }
    assert cross_download.status_code == 404
    assert audit_read.status_code == 403
    beta_file = beta["workspace"].upload_directory / f"{beta['document_id']}.pdf"
    assert beta_file.is_file()

    platform_only = User(
        email=f"platform-only-{uuid4().hex}@example.invalid",
        password_hash=hash_password("violet-cactus-orbit-sailed"),
        is_platform_admin=True,
    )
    platform_only_email = platform_only.email
    with Session(pg_engine) as db:
        db.add(platform_only)
        db.flush()
        platform_only_id = platform_only.id
        db.commit()
    test_admin_ids.append(platform_only_id)
    no_membership_login = client.post(
        "/auth/login",
        json={"email": platform_only_email, "password": "violet-cactus-orbit-sailed"},
    )
    assert no_membership_login.status_code == 200, no_membership_login.text

    platform_only_body = no_membership_login.json()
    assert platform_only_body["organisation_id"] is None
    assert platform_only_body["permissions"] == []

    platform_only_headers = {
        "Authorization": f"Bearer {platform_only_body['access_token']}"
    }

    # Independent platform authentication must not grant tenant-content access.
    platform_only_documents = client.get(
        "/documents", headers=platform_only_headers
    )
    assert platform_only_documents.status_code == 403, platform_only_documents.text

    platform_only_audit = client.get(
        "/audit/events", headers=platform_only_headers
    )
    assert platform_only_audit.status_code == 403, platform_only_audit.text


def test_postgres_concurrent_super_admin_revocations_preserve_one_operator(
    postgres_api_tenant_world, pg_engine
):
    """Concurrent mutual revocations serialize and cannot remove every super-admin."""
    client = postgres_api_tenant_world["client"]
    alpha = postgres_api_tenant_world["identities"]["alpha"]
    beta = postgres_api_tenant_world["identities"]["beta"]
    with Session(pg_engine) as db:
        db.add_all([
            PlatformRoleAssignment(
                user_id=alpha["user_id"],
                role=PlatformRole.SUPER_ADMINISTRATOR.value,
                assigned_by_user_id=alpha["user_id"],
            ),
            PlatformRoleAssignment(
                user_id=beta["user_id"],
                role=PlatformRole.SUPER_ADMINISTRATOR.value,
                assigned_by_user_id=alpha["user_id"],
            ),
        ])
        db.commit()

        active_legacy_ids = set(db.scalars(
            select(User.id).where(
                User.is_active.is_(True),
                User.is_platform_admin.is_(True),
            )
        ).all())

        active_explicit_ids = set(db.scalars(
            select(PlatformRoleAssignment.user_id)
            .join(User, User.id == PlatformRoleAssignment.user_id)
            .where(
                User.is_active.is_(True),
                PlatformRoleAssignment.role == PlatformRole.SUPER_ADMINISTRATOR.value,
            )
        ).all())

    active_before = active_legacy_ids | active_explicit_ids
    expected_operators = {alpha["user_id"], beta["user_id"]}
    assert active_before == expected_operators, (
        "Concurrency test requires exactly its two synthetic operators; "
        f"found {len(active_before)} active operators."
    )

    alpha_login = client.post(
        "/auth/login",
        json={"email": alpha["email"], "password": "violet-cactus-orbit-sailed", "auth_scope": "platform"},
    )
    beta_login = client.post(
        "/auth/login",
        json={"email": beta["email"], "password": "violet-cactus-orbit-sailed", "auth_scope": "platform"},
    )
    assert alpha_login.status_code == 200, alpha_login.text
    assert beta_login.status_code == 200, beta_login.text
    alpha_headers = {"Authorization": f"Bearer {alpha_login.json()['access_token']}"}
    beta_headers = {"Authorization": f"Bearer {beta_login.json()['access_token']}"}
    barrier = Barrier(2)

    def revoke(target_id, headers):
        barrier.wait(timeout=10)
        return client.delete(
            f"/platform/users/{target_id}/roles/platform_super_administrator",
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        alpha_revokes_beta = executor.submit(revoke, beta["user_id"], alpha_headers)
        beta_revokes_alpha = executor.submit(revoke, alpha["user_id"], beta_headers)
        responses = [alpha_revokes_beta.result(timeout=30), beta_revokes_alpha.result(timeout=30)]

    statuses = [response.status_code for response in responses]
    assert statuses.count(200) == 1, [response.text for response in responses]
    assert all(status in {200, 401, 403, 409} for status in statuses), statuses
    with Session(pg_engine) as db:
        remaining = set(db.scalars(
            select(PlatformRoleAssignment.user_id)
            .join(User, User.id == PlatformRoleAssignment.user_id)
            .where(
                User.is_active.is_(True),
                PlatformRoleAssignment.role == PlatformRole.SUPER_ADMINISTRATOR.value,
            )
        ).all())
    assert len(remaining) == 1, f"Expected exactly one active platform super-admin, found {len(remaining)}"
