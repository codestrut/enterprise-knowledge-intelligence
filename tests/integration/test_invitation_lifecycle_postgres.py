"""PostgreSQL verification of the invitation lifecycle invariants (migration 0008).

Runs only against the isolated loopback test database configured through
EKIP_TEST_DATABASE_URL (see test_auth_postgres.py). Every test uses uniquely named
records and never issues destructive cleanup.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.models import Organisation, OrganisationInvitation, TenantOnboarding, User
from tests.integration.test_auth_postgres import pg_engine  # noqa: F401  (module fixture)


def _tenant(engine):
    suffix = uuid4().hex[:12]
    with Session(engine) as db:
        organisation = Organisation(name=f"Invite Test {suffix}", slug=f"invite-test-{suffix}")
        admin = User(email=f"admin-{suffix}@example.test", password_hash="$argon2id$test-hash")
        db.add_all([organisation, admin])
        db.commit()
        return organisation.id, admin.id, suffix


def _invitation(organisation_id, admin_id, email, **overrides):
    values = {
        "organisation_id": organisation_id,
        "recipient_email": email,
        "role": "contributor",
        "token_hash": uuid4().hex + uuid4().hex,
        "invited_by_user_id": admin_id,
        "expires_at": datetime.now(UTC) + timedelta(hours=72),
    }
    values.update(overrides)
    return OrganisationInvitation(**values)


def _sqlstate(error):
    return getattr(error.orig, "sqlstate", None)


def test_invitation_lifecycle_columns_constraints_and_indexes_exist(pg_engine):
    with pg_engine.connect() as connection:
        columns = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'organisation_invitations'"
                )
            )
        }
        assert {
            "purpose",
            "revoked_at",
            "revoked_by_user_id",
            "revocation_reason",
            "superseded_by_id",
            "accepted_by_user_id",
        } <= columns

        constraints = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'organisation_invitations'::regclass"
                )
            )
        }
        assert {
            "ck_invitations_purpose_valid",
            "ck_invitations_supersession_pair",
            "uq_organisation_invitations_org_id",
            "fk_invitations_superseded_same_org",
        } <= constraints

        indexes = dict(
            connection.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename = 'organisation_invitations'"
                )
            ).all()
        )
        for name in (
            "uq_org_invitations_one_open_per_recipient",
            "uq_org_invitations_one_current_initial_admin",
        ):
            assert "UNIQUE" in indexes[name] and "WHERE" in indexes[name]

        deferrable, deferred = connection.execute(
            text(
                "SELECT condeferrable, condeferred FROM pg_constraint "
                "WHERE conname = 'fk_invitations_superseded_same_org'"
            )
        ).one()
        assert (deferrable, deferred) == (True, True)


def test_concurrent_open_invitations_for_one_recipient_allow_exactly_one(pg_engine):
    organisation_id, admin_id, suffix = _tenant(pg_engine)
    email = f"invitee-{suffix}@example.test"
    barrier = Barrier(2, timeout=10)

    def issue():
        with Session(pg_engine) as db:
            db.add(_invitation(organisation_id, admin_id, email))
            barrier.wait()
            try:
                db.commit()
                return "issued"
            except IntegrityError as error:
                db.rollback()
                assert _sqlstate(error) == "23505"
                return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(future.result(timeout=30) for future in [pool.submit(issue), pool.submit(issue)])

    assert results == ["issued", "rejected"]
    with Session(pg_engine) as db:
        open_count = db.execute(
            text(
                "SELECT count(*) FROM organisation_invitations "
                "WHERE organisation_id = :org AND accepted_at IS NULL AND revoked_at IS NULL"
            ),
            {"org": organisation_id},
        ).scalar()
    assert open_count == 1


def test_resend_closes_the_old_invitation_and_inserts_the_replacement_atomically(pg_engine):
    organisation_id, admin_id, suffix = _tenant(pg_engine)
    email = f"invitee-{suffix}@example.test"
    with Session(pg_engine) as db:
        old = _invitation(organisation_id, admin_id, email)
        db.add(old)
        db.commit()
        old_id = old.id

    replacement_id = uuid4()
    with Session(pg_engine) as db:
        old = db.get(OrganisationInvitation, old_id)
        old.revoked_at = datetime.now(UTC)
        old.revocation_reason = "superseded"
        old.superseded_by_id = replacement_id
        db.flush()
        db.add(_invitation(organisation_id, admin_id, email, id=replacement_id))
        db.commit()

    with Session(pg_engine) as db:
        rows = db.execute(
            text(
                "SELECT id, revoked_at IS NULL AS open FROM organisation_invitations "
                "WHERE organisation_id = :org"
            ),
            {"org": organisation_id},
        ).all()
    assert len(rows) == 2
    assert [row.id for row in rows if row.open] == [replacement_id]


def test_a_dangling_supersession_pointer_fails_at_commit(pg_engine):
    organisation_id, admin_id, suffix = _tenant(pg_engine)
    with Session(pg_engine) as db:
        old = _invitation(organisation_id, admin_id, f"invitee-{suffix}@example.test")
        db.add(old)
        db.commit()
        old_id = old.id

    with Session(pg_engine) as db:
        old = db.get(OrganisationInvitation, old_id)
        old.revoked_at = datetime.now(UTC)
        old.revocation_reason = "superseded"
        old.superseded_by_id = uuid4()
        db.flush()  # a deferred foreign key is not checked yet
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert _sqlstate(error.value) == "23503"


def test_supersession_cannot_cross_organisations(pg_engine):
    organisation_a, admin_a, suffix_a = _tenant(pg_engine)
    organisation_b, admin_b, suffix_b = _tenant(pg_engine)
    with Session(pg_engine) as db:
        mine = _invitation(organisation_a, admin_a, f"invitee-{suffix_a}@example.test")
        foreign = _invitation(organisation_b, admin_b, f"invitee-{suffix_b}@example.test")
        db.add_all([mine, foreign])
        db.commit()
        mine_id, foreign_id = mine.id, foreign.id

    with Session(pg_engine) as db:
        mine = db.get(OrganisationInvitation, mine_id)
        mine.revoked_at = datetime.now(UTC)
        mine.revocation_reason = "superseded"
        mine.superseded_by_id = foreign_id
        db.flush()
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert _sqlstate(error.value) == "23503"


def test_only_one_open_initial_admin_invitation_per_organisation(pg_engine):
    organisation_id, admin_id, suffix = _tenant(pg_engine)
    with Session(pg_engine) as db:
        db.add(
            _invitation(
                organisation_id,
                admin_id,
                f"first-{suffix}@example.test",
                purpose="initial_admin",
                role="organisation_administrator",
            )
        )
        db.commit()

    with Session(pg_engine) as db:
        db.add(
            _invitation(
                organisation_id,
                admin_id,
                f"second-{suffix}@example.test",
                purpose="initial_admin",
                role="organisation_administrator",
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert _sqlstate(error.value) == "23505"



def test_accepted_initial_admin_blocks_a_second_current_initial_admin_invitation(pg_engine):
    organisation_id, admin_id, suffix = _tenant(pg_engine)
    with Session(pg_engine) as db:
        accepted = _invitation(
            organisation_id,
            admin_id,
            f"first-admin-{suffix}@example.test",
            purpose="initial_admin",
            role="organisation_administrator",
            accepted_at=datetime.now(UTC),
            accepted_by_user_id=admin_id,
        )
        db.add(accepted)
        db.commit()

    with Session(pg_engine) as db:
        db.add(
            _invitation(
                organisation_id,
                admin_id,
                f"second-admin-{suffix}@example.test",
                purpose="initial_admin",
                role="organisation_administrator",
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert _sqlstate(error.value) == "23505"


def test_acceptance_without_an_accepting_user_violates_a_check(pg_engine):
    organisation_id, admin_id, suffix = _tenant(pg_engine)
    with Session(pg_engine) as db:
        db.add(
            _invitation(
                organisation_id,
                admin_id,
                f"invitee-{suffix}@example.test",
                accepted_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert _sqlstate(error.value) == "23514"


def test_onboarding_cannot_reference_another_organisations_invitation(pg_engine):
    organisation_a, admin_a, suffix_a = _tenant(pg_engine)
    organisation_b, admin_b, suffix_b = _tenant(pg_engine)
    with Session(pg_engine) as db:
        foreign = _invitation(
            organisation_b,
            admin_b,
            f"invitee-{suffix_b}@example.test",
            purpose="initial_admin",
            role="organisation_administrator",
        )
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id

    with Session(pg_engine) as db:
        db.add(
            TenantOnboarding(
                organisation_id=organisation_a,
                status="pending_admin",
                initial_admin_email=f"first-{suffix_a}@example.test",
                idempotency_key=str(uuid4()),
                request_fingerprint="f" * 64,
                created_by_user_id=admin_a,
                initial_admin_invitation_id=foreign_id,
            )
        )
        with pytest.raises(IntegrityError) as error:
            db.commit()
        assert _sqlstate(error.value) == "23503"
