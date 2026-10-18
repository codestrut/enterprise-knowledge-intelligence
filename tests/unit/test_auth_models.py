from uuid import UUID

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.models import Base, Organisation, OrganisationMembership, User
from src.auth.permissions import Permission, Role


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


def make_user(email="reader@example.com"):
    return User(email=email, password_hash="$argon2id$test-hash")


def test_models_have_stable_uuid_ids_timestamps_and_bidirectional_relationships(session):
    organisation = Organisation(name=" Example Org ", slug=" Example-Org ")
    user = make_user(" Reader@Example.com ")
    membership = OrganisationMembership(role=Role.READER)
    membership.organisation = organisation
    membership.user = user
    session.add(membership)
    session.commit()

    assert isinstance(organisation.id, UUID)
    assert isinstance(user.id, UUID)
    assert isinstance(membership.id, UUID)
    assert organisation.name == "Example Org"
    assert organisation.slug == "example-org"
    assert user.email == "reader@example.com"
    assert membership.organisation is organisation
    assert membership.user is user
    assert user.memberships == [membership]
    assert organisation.memberships == [membership]
    assert organisation.created_at is not None
    assert organisation.updated_at is not None


def test_membership_role_resolves_through_existing_permission_catalog(session):
    organisation = Organisation(name="Example", slug="example")
    user = make_user()
    membership = OrganisationMembership(
        organisation=organisation, user=user, role=Role.READER
    )
    session.add(membership)
    session.commit()

    assert membership.role is Role.READER
    assert membership.permissions == frozenset(
        {Permission.DOCUMENTS_READ, Permission.DOCUMENTS_QUERY}
    )


def test_duplicate_membership_is_rejected_by_database_constraint(session):
    organisation = Organisation(name="Example", slug="example")
    user = make_user()
    session.add_all(
        [
            OrganisationMembership(organisation=organisation, user=user, role=Role.READER),
            OrganisationMembership(organisation=organisation, user=user, role=Role.CONTRIBUTOR),
        ]
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_normalized_user_identity_is_unique(session):
    session.add(make_user(" Person@Example.com "))
    session.commit()
    assert session.scalar(select(User.email)) == "person@example.com"

    session.add(make_user("PERSON@example.com"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_membership_foreign_keys_reject_unknown_records(session):
    session.add(
        OrganisationMembership(
            organisation_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id=UUID("00000000-0000-0000-0000-000000000002"),
            role=Role.READER,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_model_representations_do_not_include_email_or_password_hash():
    secret_hash = "$argon2id$v=19$m=65536,t=3,p=4$not-a-real-secret-hash"
    user = User(email="private@example.com", password_hash=secret_hash)

    assert "private@example.com" not in repr(user)
    assert secret_hash not in repr(user)


def test_empty_user_identity_and_organisation_names_are_rejected():
    with pytest.raises(ValueError):
        User(email="   ", password_hash="$argon2id$test")
    with pytest.raises(ValueError):
        Organisation(name=" ", slug="example")
    with pytest.raises(ValueError):
        Organisation(name="Example", slug=" ")


def test_plaintext_password_cannot_be_assigned_to_a_user_model():
    with pytest.raises(ValueError, match="Only an Argon2id password hash"):
        User(email="person@example.com", password_hash="plaintext-password")


def test_database_constraint_rejects_plaintext_password_hash_values(session):
    with pytest.raises(IntegrityError):
        session.execute(
            User.__table__.insert().values(
                email="person@example.com",
                password_hash="plaintext-password",
            )
        )
        session.commit()
