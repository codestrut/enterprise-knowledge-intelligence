from datetime import UTC, datetime, timedelta
import hashlib
import secrets

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session as OrmSession

from src.auth.models import (
    AuditEvent,
    Base,
    Organisation,
    OrganisationMembership,
    RefreshSessionRecord,
    User,
)
from src.auth.permissions import Permission, Role
from src.auth.passwords import hash_password
from src.auth.service import (
    AuthenticationError,
    OrganisationSelection,
    authenticate_managed_user,
    login_managed_user,
    revoke_refresh_session,
    rotate_refresh_session,
)


VALID_PASSWORD = "violet-cactus-orbit-sailed"


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with OrmSession(engine) as db_session:
        yield db_session
    engine.dispose()


def add_identity(session, *, active=True, membership_active=True, role=Role.READER):
    organisation = Organisation(name="Example", slug="example")
    user = User(
        email="reader@example.com",
        password_hash=hash_password(VALID_PASSWORD),
        is_active=active,
    )
    membership = OrganisationMembership(
        organisation=organisation,
        user=user,
        role=role,
        is_active=membership_active,
    )
    session.add_all([organisation, user, membership])
    session.commit()
    return user, organisation, membership


def test_valid_auth_resolves_persisted_membership_permissions_and_closes_transaction(session):
    user, organisation, membership = add_identity(session)
    user_id, organisation_id, membership_id = user.id, organisation.id, membership.id

    principal = authenticate_managed_user(session, " READER@example.com ", VALID_PASSWORD)

    assert not session.in_transaction()
    assert principal.user_id == user_id
    assert principal.membership_id == membership_id
    assert principal.organisation_id == organisation_id
    assert principal.role is Role.READER
    assert principal.permissions == frozenset(
        {Permission.DOCUMENTS_READ, Permission.DOCUMENTS_QUERY}
    )


def test_invalid_credentials_are_non_revealing_close_transaction_and_issue_no_session(session):
    user, organisation, _membership = add_identity(session)
    with pytest.raises(AuthenticationError) as known_user:
        login_managed_user(session, "reader@example.com", "wrong password")
    assert not session.in_transaction()
    with pytest.raises(AuthenticationError) as unknown_user:
        login_managed_user(session, "missing@example.com", "wrong password")

    assert str(known_user.value) == str(unknown_user.value)
    assert not session.in_transaction()
    assert session.scalar(select(RefreshSessionRecord.id)) is None
    events = session.scalars(select(AuditEvent).where(AuditEvent.event_type == "auth.login_failed")).all()
    assert len(events) == 2
    known_event = next(event for event in events if event.actor_user_id == user.id)
    assert known_event.organisation_id == organisation.id
    assert known_event.details == {"action": "login", "outcome": "failure", "reason": "invalid_credentials"}
    assert "wrong password" not in str(known_event.details)
    assert "reader@example.com" not in str(known_event.details)
    unknown_event = next(event for event in events if event.actor_user_id is None)
    assert unknown_event.organisation_id is None


def test_failed_login_audit_persistence_failure_does_not_return_ordinary_auth_failure(session, monkeypatch):
    add_identity(session)

    def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(session, "commit", fail_commit)
    from src.auth.service import AuditPersistenceError

    with pytest.raises(AuditPersistenceError):
        login_managed_user(session, "reader@example.com", "wrong password")
    assert not session.in_transaction()
    assert session.scalar(select(RefreshSessionRecord.id)) is None


@pytest.mark.parametrize(
    ("user_active", "membership_active"),
    [(False, True), (True, False)],
)
def test_inactive_user_or_membership_cannot_authenticate(
    session, user_active, membership_active
):
    add_identity(session, active=user_active, membership_active=membership_active)

    with pytest.raises(AuthenticationError):
        login_managed_user(session, "reader@example.com", VALID_PASSWORD)
    assert session.scalar(select(RefreshSessionRecord.id)) is None


def test_multiple_active_organisations_are_returned_only_after_valid_credentials(session):
    user, first_org, _first_membership = add_identity(session)
    user_email, first_org_id = user.email, first_org.id
    second_org = Organisation(name="Second", slug="second")
    second_membership = OrganisationMembership(
        organisation=second_org, user=user, role=Role.CONTRIBUTOR
    )
    inactive_org = Organisation(name="Inactive", slug="inactive", is_active=False)
    inactive_membership = OrganisationMembership(
        organisation=inactive_org, user=user, role=Role.ORGANISATION_ADMINISTRATOR
    )
    session.add_all([second_org, second_membership, inactive_org, inactive_membership])
    session.commit()

    with pytest.raises(AuthenticationError):
        authenticate_managed_user(session, user_email, "incorrect password long")
    choices = authenticate_managed_user(session, user_email, VALID_PASSWORD)
    assert not session.in_transaction()
    assert isinstance(choices, OrganisationSelection)
    assert {item.id for item in choices.organisations} == {first_org.id, second_org.id}
    assert all(not hasattr(item, "role") for item in choices.organisations)

    login_choices = login_managed_user(session, user_email, VALID_PASSWORD)
    assert isinstance(login_choices, OrganisationSelection)
    assert session.scalar(select(RefreshSessionRecord.id)) is None

    grant = login_managed_user(
        session,
        user_email,
        VALID_PASSWORD,
        organisation_id=first_org_id,
    )
    assert grant.principal.organisation_id == first_org_id


def test_client_cannot_select_an_organisation_without_a_persisted_membership(session):
    user, organisation, _membership = add_identity(session)
    other = Organisation(name="Not joined", slug="not-joined")
    session.add(other)
    session.commit()

    with pytest.raises(AuthenticationError):
        login_managed_user(
            session,
            user.email,
            VALID_PASSWORD,
            organisation_id=other.id,
        )
    assert session.scalar(select(RefreshSessionRecord.id)) is None


def test_login_stores_only_hash_of_refresh_token_and_bounds_session_family(session):
    add_identity(session)
    created = datetime(2026, 10, 1, tzinfo=UTC)
    grant = login_managed_user(session, "reader@example.com", VALID_PASSWORD, now=created)

    record = session.scalar(select(RefreshSessionRecord))
    assert record is not None
    assert len(grant.refresh_token) >= 40
    assert record.token_hash == hashlib.sha256(grant.refresh_token.encode()).hexdigest()
    assert grant.refresh_token not in record.token_hash
    assert grant.refresh_token not in repr(record)
    assert grant.refresh_token not in repr(grant)
    assert record.expires_at.replace(tzinfo=UTC) == created + timedelta(days=7)
    assert record.family_expires_at.replace(tzinfo=UTC) == created + timedelta(days=30)


def test_rotation_retry_with_same_key_returns_same_replacement(session):
    add_identity(session)
    first = login_managed_user(session, "reader@example.com", VALID_PASSWORD)
    rotation_key = secrets.token_urlsafe(32)

    second = rotate_refresh_session(session, first.refresh_token, rotation_key)
    retry = rotate_refresh_session(session, first.refresh_token, rotation_key)

    assert retry.refresh_token == second.refresh_token
    assert retry.principal == second.principal
    assert session.scalar(
        select(RefreshSessionRecord.id).where(RefreshSessionRecord.revoked_at.is_(None))
    ) is not None
    assert len(list(session.scalars(select(RefreshSessionRecord)))) == 2


def test_old_token_without_matching_retry_key_cannot_recover_token_and_triggers_reuse_detection(session):
    add_identity(session)
    first = login_managed_user(session, "reader@example.com", VALID_PASSWORD)
    second = rotate_refresh_session(session, first.refresh_token, secrets.token_urlsafe(32))

    with pytest.raises(AuthenticationError):
        rotate_refresh_session(session, first.refresh_token, secrets.token_urlsafe(32))
    session.expire_all()
    second_record = session.scalar(
        select(RefreshSessionRecord).where(
            RefreshSessionRecord.token_hash == hashlib.sha256(second.refresh_token.encode()).hexdigest()
        )
    )
    assert second_record.revoked_at is not None
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "auth.session_reuse_detected")
    ) is not None


def test_idle_expiry_revokes_session_family(session):
    add_identity(session)
    created = datetime(2026, 10, 1, tzinfo=UTC)
    grant = login_managed_user(session, "reader@example.com", VALID_PASSWORD, now=created)

    with pytest.raises(AuthenticationError):
        rotate_refresh_session(
            session,
            grant.refresh_token,
            secrets.token_urlsafe(32),
            now=created + timedelta(days=7),
        )
    record = session.scalar(select(RefreshSessionRecord))
    assert record.revoked_at.replace(tzinfo=UTC) == created + timedelta(days=7)


def test_absolute_family_lifetime_cannot_be_extended_by_rotation(session):
    add_identity(session)
    created = datetime(2026, 10, 1, tzinfo=UTC)
    grant = login_managed_user(session, "reader@example.com", VALID_PASSWORD, now=created)
    token = grant.refresh_token
    for day in (6, 12, 18, 24):
        grant = rotate_refresh_session(
            session,
            token,
            secrets.token_urlsafe(32),
            now=created + timedelta(days=day),
        )
        token = grant.refresh_token

    with pytest.raises(AuthenticationError):
        rotate_refresh_session(
            session,
            token,
            secrets.token_urlsafe(32),
            now=created + timedelta(days=30),
        )


def test_logout_is_idempotent_audited_and_revokes_token(session, caplog):
    add_identity(session)
    grant = login_managed_user(session, "reader@example.com", VALID_PASSWORD)
    revoke_refresh_session(session, grant.refresh_token)
    revoke_refresh_session(session, grant.refresh_token)

    record = session.scalar(select(RefreshSessionRecord))
    assert record.revoked_at is not None
    assert grant.refresh_token not in caplog.text
    assert session.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "auth.session_revoked")
    ) is not None
    with pytest.raises(AuthenticationError):
        rotate_refresh_session(session, grant.refresh_token, secrets.token_urlsafe(32))


def test_invalid_refresh_tokens_are_rejected_and_invalid_logout_is_harmless(session):
    with pytest.raises(AuthenticationError):
        rotate_refresh_session(session, "not-a-session-token", secrets.token_urlsafe(32))
    revoke_refresh_session(session, None)
    assert session.scalar(select(RefreshSessionRecord.id)) is None


def test_disabled_membership_or_organisation_revokes_existing_session_on_refresh(session):
    _user, organisation, membership = add_identity(session)
    grant = login_managed_user(session, "reader@example.com", VALID_PASSWORD)
    membership.is_active = False
    session.commit()

    with pytest.raises(AuthenticationError):
        rotate_refresh_session(session, grant.refresh_token, secrets.token_urlsafe(32))
    record = session.scalar(select(RefreshSessionRecord))
    assert record.revoked_at is not None

    membership.is_active = True
    organisation.is_active = False
    session.commit()
    with pytest.raises(AuthenticationError):
        login_managed_user(session, "reader@example.com", VALID_PASSWORD)


def test_audit_records_do_not_contain_token_or_hash_and_persist_across_sessions(session):
    add_identity(session)
    grant = login_managed_user(session, "reader@example.com", VALID_PASSWORD)
    engine = session.get_bind()

    with OrmSession(engine) as reopened_session:
        record = reopened_session.scalar(select(RefreshSessionRecord))
        event = reopened_session.scalar(select(AuditEvent))
        assert record is not None and event is not None
        assert record.token_hash == hashlib.sha256(grant.refresh_token.encode()).hexdigest()
        assert grant.refresh_token not in repr(event)
        assert record.token_hash not in repr(event)
        assert event.event_type == "auth.session_created"
