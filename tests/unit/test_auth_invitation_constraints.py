"""Database invariants for the invitation lifecycle (migration 0008, SQLite model view)."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.models import Base, Organisation, OrganisationInvitation, TenantOnboarding, User


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session
    engine.dispose()


@pytest.fixture
def world(session):
    org_a = Organisation(name="Alpha", slug="alpha")
    org_b = Organisation(name="Beta", slug="beta")
    admin_a = User(email="admin-a@example.test", password_hash="$argon2id$test-hash")
    admin_b = User(email="admin-b@example.test", password_hash="$argon2id$test-hash")
    session.add_all([org_a, org_b, admin_a, admin_b])
    session.commit()
    return SimpleNamespace(org_a=org_a, org_b=org_b, admin_a=admin_a, admin_b=admin_b)


def make_invitation(session, organisation, inviter, email="invitee@example.test", **overrides):
    values = {
        "organisation_id": organisation.id,
        "recipient_email": email,
        "role": "contributor",
        "token_hash": uuid4().hex + uuid4().hex,
        "invited_by_user_id": inviter.id,
        "expires_at": datetime.now(UTC) + timedelta(hours=72),
    }
    values.update(overrides)
    invitation = OrganisationInvitation(**values)
    session.add(invitation)
    session.flush()
    return invitation


def assert_rejected(session, action, at_commit=False):
    """Expect an integrity error. Deferred foreign keys are only checked at commit."""
    with pytest.raises(IntegrityError):
        action()
        session.flush()
        if at_commit:
            session.commit()
    session.rollback()


def test_new_invitations_are_open_member_invitations(session, world):
    invitation = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    assert invitation.purpose == "member"
    assert invitation.revoked_at is None
    assert invitation.accepted_at is None
    assert invitation.superseded_by_id is None


def test_purpose_must_be_known(session, world):
    assert_rejected(
        session, lambda: make_invitation(session, world.org_a, world.admin_a, purpose="owner")
    )


def test_initial_admin_invitation_must_target_the_administrator_role(session, world):
    assert_rejected(
        session,
        lambda: make_invitation(
            session, world.org_a, world.admin_a, purpose="initial_admin", role="reader"
        ),
    )
    make_invitation(
        session,
        world.org_a,
        world.admin_a,
        purpose="initial_admin",
        role="organisation_administrator",
    )
    session.commit()


def test_revocation_needs_a_reason_and_a_reason_needs_revocation(session, world):
    now = datetime.now(UTC)
    invitation = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    invitation.revoked_at = now
    assert_rejected(session, lambda: None)

    invitation = session.get(OrganisationInvitation, invitation.id)
    invitation.revocation_reason = "revoked_by_admin"
    assert_rejected(session, lambda: None)

    invitation = session.get(OrganisationInvitation, invitation.id)
    invitation.revoked_at = now
    invitation.revocation_reason = "revoked_by_admin"
    invitation.revoked_by_user_id = world.admin_a.id
    session.commit()


def test_revocation_reason_must_be_known(session, world):
    invitation = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    invitation.revoked_at = datetime.now(UTC)
    invitation.revocation_reason = "because"
    assert_rejected(session, lambda: None)


def test_acceptance_needs_the_accepting_user_and_the_reverse(session, world):
    invitation = make_invitation(session, world.org_a, world.admin_a)
    session.commit()
    invitation_id = invitation.id
    accepting_user_id = world.admin_b.id

    invitation.accepted_at = datetime.now(UTC)
    assert_rejected(session, lambda: None)

    invitation = session.get(OrganisationInvitation, invitation_id)
    invitation.accepted_by_user_id = accepting_user_id
    assert_rejected(session, lambda: None)

    invitation = session.get(OrganisationInvitation, invitation_id)
    invitation.accepted_at = datetime.now(UTC)
    invitation.accepted_by_user_id = accepting_user_id
    session.commit()


def test_an_invitation_cannot_be_both_accepted_and_revoked(session, world):
    invitation = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    now = datetime.now(UTC)
    accepting_user_id = world.admin_b.id
    invitation.accepted_at = now
    invitation.accepted_by_user_id = accepting_user_id
    invitation.revoked_at = now
    invitation.revocation_reason = "revoked_by_admin"
    assert_rejected(session, lambda: None)


def test_a_revoker_requires_a_revocation(session, world):
    invitation = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    invitation.revoked_by_user_id = world.admin_a.id
    assert_rejected(session, lambda: None)


def test_supersession_needs_matching_reason_and_pointer(session, world):
    first = make_invitation(session, world.org_a, world.admin_a)
    second = make_invitation(session, world.org_a, world.admin_a, email="other@example.test")
    session.commit()
    first_id, second_id = first.id, second.id
    now = datetime.now(UTC)

    # reason without a pointer
    first.revoked_at = now
    first.revocation_reason = "superseded"
    assert_rejected(session, lambda: None)

    # pointer with a different reason
    first = session.get(OrganisationInvitation, first_id)
    first.revoked_at = now
    first.revocation_reason = "revoked_by_admin"
    first.superseded_by_id = second_id
    assert_rejected(session, lambda: None)

    # pointer to itself
    first = session.get(OrganisationInvitation, first_id)
    first.revoked_at = now
    first.revocation_reason = "superseded"
    first.superseded_by_id = first_id
    assert_rejected(session, lambda: None)


def test_supersession_cannot_point_into_another_organisation(session, world):
    first = make_invitation(session, world.org_a, world.admin_a)
    foreign = make_invitation(session, world.org_b, world.admin_b)
    session.commit()
    foreign_id = foreign.id

    first.revoked_at = datetime.now(UTC)
    first.revocation_reason = "superseded"
    first.superseded_by_id = foreign_id
    assert_rejected(session, lambda: None, at_commit=True)


def test_resend_supersedes_the_open_invitation_in_one_transaction(session, world):
    old = make_invitation(session, world.org_a, world.admin_a)
    session.commit()
    old_id = old.id

    # Service order: close the old invitation first (the one-open-invitation index
    # requires it), pointing at the id of the replacement, then insert the
    # replacement. The pointer is a deferred foreign key checked at commit.
    replacement_id = uuid4()
    old.revoked_at = datetime.now(UTC)
    old.revocation_reason = "superseded"
    old.superseded_by_id = replacement_id
    session.flush()
    make_invitation(session, world.org_a, world.admin_a, id=replacement_id)
    session.commit()

    refreshed = session.get(OrganisationInvitation, old_id)
    assert refreshed.superseded_by_id == replacement_id
    assert refreshed.revocation_reason == "superseded"


def test_a_dangling_supersession_pointer_is_rejected_at_commit(session, world):
    old = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    old.revoked_at = datetime.now(UTC)
    old.revocation_reason = "superseded"
    old.superseded_by_id = uuid4()
    assert_rejected(session, lambda: None, at_commit=True)


def test_only_one_open_invitation_per_recipient_and_organisation(session, world):
    first = make_invitation(session, world.org_a, world.admin_a)
    session.commit()

    assert_rejected(session, lambda: make_invitation(session, world.org_a, world.admin_a))

    # another organisation may invite the same address
    make_invitation(session, world.org_b, world.admin_b)
    session.commit()

    # a revoked invitation frees the slot
    first = session.get(OrganisationInvitation, first.id)
    first.revoked_at = datetime.now(UTC)
    first.revocation_reason = "revoked_by_admin"
    session.commit()
    make_invitation(session, world.org_a, world.admin_a)
    session.commit()


def test_an_accepted_invitation_frees_the_recipient_slot(session, world):
    first = make_invitation(session, world.org_a, world.admin_a)
    session.commit()
    accepting_user_id = world.admin_b.id
    first.accepted_at = datetime.now(UTC)
    first.accepted_by_user_id = accepting_user_id
    session.commit()

    make_invitation(session, world.org_a, world.admin_a)
    session.commit()


def test_only_one_open_initial_admin_invitation_per_organisation(session, world):
    make_invitation(
        session,
        world.org_a,
        world.admin_a,
        email="first-admin@example.test",
        purpose="initial_admin",
        role="organisation_administrator",
    )
    session.commit()

    assert_rejected(
        session,
        lambda: make_invitation(
            session,
            world.org_a,
            world.admin_a,
            email="second-admin@example.test",
            purpose="initial_admin",
            role="organisation_administrator",
        ),
    )


def test_only_one_initial_admin_invitation_can_ever_be_accepted(session, world):
    accepted_at = datetime.now(UTC)
    make_invitation(
        session,
        world.org_a,
        world.admin_a,
        email="first-admin@example.test",
        purpose="initial_admin",
        role="organisation_administrator",
        accepted_at=accepted_at,
        accepted_by_user_id=world.admin_b.id,
    )
    session.commit()

    assert_rejected(
        session,
        lambda: make_invitation(
            session,
            world.org_a,
            world.admin_a,
            email="second-admin@example.test",
            purpose="initial_admin",
            role="organisation_administrator",
            accepted_at=accepted_at,
            accepted_by_user_id=world.admin_a.id,
        ),
    )


def make_onboarding(session, organisation, creator, **overrides):
    values = {
        "organisation_id": organisation.id,
        "status": "pending_admin",
        "initial_admin_email": "first-admin@example.test",
        "idempotency_key": str(uuid4()),
        "request_fingerprint": "f" * 64,
        "created_by_user_id": creator.id,
    }
    values.update(overrides)
    onboarding = TenantOnboarding(**values)
    session.add(onboarding)
    session.flush()
    return onboarding


def test_onboarding_acceptance_needs_an_invitation_reference(session, world):
    assert_rejected(
        session,
        lambda: make_onboarding(
            session,
            world.org_a,
            world.admin_a,
            initial_admin_invitation_accepted_at=datetime.now(UTC),
        ),
    )


def test_onboarding_may_reference_its_own_organisations_invitation(session, world):
    invitation = make_invitation(
        session,
        world.org_a,
        world.admin_a,
        purpose="initial_admin",
        role="organisation_administrator",
    )
    make_onboarding(
        session,
        world.org_a,
        world.admin_a,
        initial_admin_invitation_id=invitation.id,
        initial_admin_invitation_accepted_at=datetime.now(UTC),
    )
    session.commit()


def test_onboarding_cannot_reference_another_organisations_invitation(session, world):
    foreign = make_invitation(
        session,
        world.org_b,
        world.admin_b,
        purpose="initial_admin",
        role="organisation_administrator",
    )
    session.commit()

    assert_rejected(
        session,
        lambda: make_onboarding(
            session, world.org_a, world.admin_a, initial_admin_invitation_id=foreign.id
        ),
    )


def test_active_onboarding_rows_without_an_invitation_remain_valid(session, world):
    """The activation predicate is a service rule. Existing API tests rely on this."""
    make_onboarding(session, world.org_a, world.admin_a, status="active")
    session.commit()


def test_accepted_initial_admin_invitation_blocks_a_second_current_invitation(session, world):
    accepted = make_invitation(
        session,
        world.org_a,
        world.admin_a,
        email="first-admin@example.test",
        purpose="initial_admin",
        role="organisation_administrator",
        accepted_at=datetime.now(UTC),
        accepted_by_user_id=world.admin_b.id,
    )
    session.commit()
    assert accepted.accepted_at is not None

    assert_rejected(
        session,
        lambda: make_invitation(
            session,
            world.org_a,
            world.admin_a,
            email="second-admin@example.test",
            purpose="initial_admin",
            role="organisation_administrator",
        ),
    )
