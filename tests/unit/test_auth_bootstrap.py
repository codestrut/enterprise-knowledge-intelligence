import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from src.auth.bootstrap import bootstrap_organisation, bootstrap_platform_admin
from src.auth.models import AuditEvent, Base, Organisation, OrganisationMembership, User
from src.auth.passwords import hash_password
from src.auth.permissions import Role


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_platform_admin_bootstrap_is_user_scoped_and_repeatable(db):
    encoded = hash_password("violet-cactus-orbit-sailed")
    assert bootstrap_platform_admin(db, "ROOT@example.com", encoded) == "created"
    assert bootstrap_platform_admin(db, "root@example.com", encoded) == "already_configured"

    user = db.scalar(select(User).where(User.email == "root@example.com"))
    assert user.is_platform_admin is True
    assert db.scalar(select(OrganisationMembership.id)) is None
    assert db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "platform.bootstrap_admin_created")
    ) is not None


def test_platform_bootstrap_never_promotes_existing_managed_user(db):
    db.add(User(email="person@example.com", password_hash=hash_password("violet-cactus-orbit-sailed")))
    db.commit()

    with pytest.raises(ValueError, match="did not change it"):
        bootstrap_platform_admin(db, "person@example.com", hash_password("another-secure-phrase"))
    assert db.scalar(select(User.is_platform_admin).where(User.email == "person@example.com")) is False


def test_organisation_bootstrap_creates_managed_admin_without_platform_privileges(db):
    encoded = hash_password("violet-cactus-orbit-sailed")
    assert bootstrap_organisation(
        db,
        name="Example Org",
        slug="Example-Org",
        admin_email="ORG-ADMIN@example.com",
        password_hash=encoded,
    ) == "created"
    assert bootstrap_organisation(
        db,
        name="Example Org",
        slug="example-org",
        admin_email="org-admin@example.com",
    ) == "already_configured"

    user = db.scalar(select(User).where(User.email == "org-admin@example.com"))
    organisation = db.scalar(select(Organisation))
    membership = db.scalar(select(OrganisationMembership))
    assert user.is_platform_admin is False
    assert organisation.slug == "example-org"
    assert membership.role is Role.ORGANISATION_ADMINISTRATOR
    assert db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "organisation.bootstrap_created")
    ) is not None


def test_organisation_bootstrap_does_not_change_existing_non_admin_membership(db):
    user = User(email="reader@example.com", password_hash=hash_password("violet-cactus-orbit-sailed"))
    organisation = Organisation(name="Example", slug="example")
    membership = OrganisationMembership(
        user=user, organisation=organisation, role=Role.READER
    )
    db.add_all([user, organisation, membership])
    db.commit()

    with pytest.raises(ValueError, match="did not change it"):
        bootstrap_organisation(
            db,
            name="Example",
            slug="example",
            admin_email="reader@example.com",
        )
    db.refresh(membership)
    assert membership.role is Role.READER


# --- Run A (B5): bootstrap must not silently add administrators to existing organisations ----


def _existing_organisation(db, name="Existing Org", slug="existing-org"):
    organisation = Organisation(name=name, slug=slug)
    db.add(organisation)
    db.commit()
    return organisation


def test_organisation_bootstrap_refuses_new_admin_for_existing_organisation(db):
    _existing_organisation(db)
    with pytest.raises(ValueError, match="--allow-existing-org"):
        bootstrap_organisation(
            db,
            name="Existing Org",
            slug="existing-org",
            admin_email="new-admin@example.com",
            password_hash=hash_password("violet-cactus-orbit-sailed"),
        )
    assert db.scalar(select(User).where(User.email == "new-admin@example.com")) is None
    assert db.scalar(select(OrganisationMembership)) is None


def test_organisation_bootstrap_override_adds_admin_and_records_audit(db):
    organisation = _existing_organisation(db)
    result = bootstrap_organisation(
        db,
        name="Existing Org",
        slug="existing-org",
        admin_email="second-admin@example.com",
        password_hash=hash_password("violet-cactus-orbit-sailed"),
        allow_existing_org=True,
    )
    assert result == "admin_added"
    membership = db.scalar(select(OrganisationMembership))
    assert membership.organisation_id == organisation.id
    assert membership.role is Role.ORGANISATION_ADMINISTRATOR
    event = db.scalar(
        select(AuditEvent).where(AuditEvent.event_type == "organisation.bootstrap_admin_added")
    )
    assert event is not None
    assert event.details == {
        "membership_id": str(membership.id),
        "source": "bootstrap_cli",
        "existing_organisation": True,
    }


def test_organisation_bootstrap_refuses_mismatched_name_for_existing_slug(db):
    _existing_organisation(db)
    with pytest.raises(ValueError, match="name does not match"):
        bootstrap_organisation(
            db,
            name="Different Name",
            slug="existing-org",
            admin_email="second-admin@example.com",
            password_hash=hash_password("violet-cactus-orbit-sailed"),
            allow_existing_org=True,
        )
    assert db.scalar(select(OrganisationMembership)) is None


def test_bootstrap_cli_requires_explicit_override_and_never_prints_the_password(monkeypatch, tmp_path, capsys):
    from src.auth import bootstrap

    url = f"sqlite+pysqlite:///{tmp_path / 'bootstrap.sqlite'}"
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _existing_organisation(session)
    monkeypatch.setattr(bootstrap, "database_url_from_environment", lambda: url)
    monkeypatch.setattr(bootstrap, "getpass", lambda _prompt: "violet-cactus-orbit-sailed")
    arguments = [
        "organisation", "--name", "Existing Org", "--slug", "existing-org",
        "--admin-email", "cli-admin@example.com", "--confirm",
    ]

    assert bootstrap.main(arguments) == 2
    refused = capsys.readouterr()
    assert "--allow-existing-org" in refused.err
    assert "violet-cactus-orbit-sailed" not in refused.out + refused.err

    assert bootstrap.main(arguments + ["--allow-existing-org"]) == 0
    allowed = capsys.readouterr()
    assert "violet-cactus-orbit-sailed" not in allowed.out + allowed.err
    with Session(engine) as session:
        membership = session.scalar(select(OrganisationMembership))
        assert membership is not None and membership.role is Role.ORGANISATION_ADMINISTRATOR
    engine.dispose()
