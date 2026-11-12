"""Persistence tests for platform-led tenant creation and provisioning state."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.auth.models import AuditEvent, Base, Organisation, TenantOnboarding, User
from src.auth.tenant_onboarding import (
    TenantOnboardingConflict,
    approve_and_provision_platform_organisation,
    create_platform_organisation,
    retry_platform_organisation_provisioning,
    recover_stale_platform_organisation_provisioning,
)


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        actor = User(
            id=uuid4(), email="platform@example.org", password_hash="$argon2id$test",
            is_platform_admin=True,
        )
        session.add(actor)
        session.commit()
        session.info["actor_id"] = actor.id
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def create(db, *, key="request-001", slug="example-org"):
    return create_platform_organisation(
        db,
        actor_user_id=db.info["actor_id"],
        name="Example Organisation",
        slug=slug,
        initial_admin_email=" Owner@Example.org ",
        idempotency_key=key,
    )


def approve(db, created, provision=lambda _org_id: object(), reason="Reviewed and approved"):
    return approve_and_provision_platform_organisation(
        db,
        actor_user_id=db.info["actor_id"],
        organisation_id=created.organisation_id,
        approval_reason=reason,
        provision_workspace=provision,
    )


def test_creation_persists_inactive_tenant_pending_explicit_approval(db):
    result = create(db)
    organisation = db.get(Organisation, result.organisation_id)
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == result.organisation_id))
    events = db.scalars(select(AuditEvent).where(AuditEvent.organisation_id == result.organisation_id)).all()

    assert result.status == "registration_pending"
    assert result.initial_admin_email == "owner@example.org"
    assert organisation is not None and organisation.is_active is False
    assert record is not None and record.provisioning_attempts == 0
    assert [event.event_type for event in events] == ["tenant_created_pending_approval"]


def test_idempotent_creation_replay_returns_same_tenant_without_duplicate_rows(db):
    first = create(db)
    replay = create(db)

    assert first.organisation_id == replay.organisation_id
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.status == "registration_pending"
    assert len(db.scalars(select(Organisation)).all()) == 1
    assert len(db.scalars(select(TenantOnboarding)).all()) == 1


def test_same_idempotency_key_with_different_payload_conflicts(db):
    create(db, key="same-key")
    with pytest.raises(TenantOnboardingConflict):
        create_platform_organisation(
            db,
            actor_user_id=db.info["actor_id"],
            name="Different Organisation",
            slug="different-org",
            initial_admin_email="owner@example.org",
            idempotency_key="same-key",
        )


def test_slug_collision_with_new_idempotency_key_conflicts(db):
    create(db, key="first-key", slug="shared-slug")
    with pytest.raises(TenantOnboardingConflict):
        create(db, key="second-key", slug="shared-slug")


def test_approval_provisions_and_leaves_tenant_inactive_until_admin_activation(db):
    created = create(db)
    result = approve(db, created)
    organisation = db.get(Organisation, result.organisation_id)
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == result.organisation_id))
    events = db.scalars(select(AuditEvent).where(AuditEvent.organisation_id == result.organisation_id)).all()

    assert result.status == "pending_admin"
    assert result.provisioning_attempts == 1
    assert organisation is not None and organisation.is_active is False
    assert record is not None and record.approved_by_user_id == db.info["actor_id"]
    assert record.provisioning_completed_at is not None
    started_event = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "tenant_provisioning_started"))
    assert started_event.details["creator_also_approver"] is True
    assert "approval_separation_exception" not in started_event.details
    assert {event.event_type for event in events} == {
        "tenant_created_pending_approval", "tenant_provisioning_started", "tenant_provisioning_completed"
    }


def test_provisioning_failure_is_persisted_without_private_exception_details(db):
    created = create(db)

    def fail(_org_id):
        raise OSError("private filesystem detail must not be stored")

    result = approve(db, created, provision=fail)
    organisation = db.get(Organisation, result.organisation_id)
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == result.organisation_id))
    events = db.scalars(select(AuditEvent).where(AuditEvent.organisation_id == result.organisation_id)).all()

    assert result.status == "provisioning_failed"
    assert organisation is not None and organisation.is_active is False
    assert record is not None and record.provisioning_error_code == "workspace_provisioning_failed"
    assert "private filesystem detail" not in str(record.provisioning_error_code)
    assert any(event.event_type == "tenant_provisioning_failed" for event in events)


def test_failed_provisioning_can_be_retried_and_recovers_to_pending_admin(db):
    created = create(db)
    failed = approve(db, created, provision=lambda _org_id: (_ for _ in ()).throw(OSError()))
    recovered = retry_platform_organisation_provisioning(
        db,
        actor_user_id=db.info["actor_id"],
        organisation_id=created.organisation_id,
        reason="Storage issue has been resolved",
        provision_workspace=lambda _org_id: object(),
    )
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == created.organisation_id))
    events = db.scalars(select(AuditEvent).where(AuditEvent.organisation_id == created.organisation_id)).all()

    assert failed.status == "provisioning_failed"
    assert recovered.status == "pending_admin"
    assert recovered.provisioning_attempts == 2
    assert record is not None and record.provisioning_error_code is None
    assert {event.event_type for event in events} >= {
        "tenant_provisioning_failed", "tenant_provisioning_retried", "tenant_provisioning_completed"
    }


def test_provisioning_retry_rejects_non_failed_tenant(db):
    created = create(db)
    approve(db, created)
    with pytest.raises(TenantOnboardingConflict):
        retry_platform_organisation_provisioning(
            db,
            actor_user_id=db.info["actor_id"],
            organisation_id=created.organisation_id,
            reason="Must not retry successful provisioning",
            provision_workspace=lambda _org_id: object(),
        )


def test_approval_cannot_repeat_after_provisioning_failure_without_retry(db):
    created = create(db)
    approve(db, created, provision=lambda _org_id: (_ for _ in ()).throw(OSError()))
    with pytest.raises(TenantOnboardingConflict):
        approve(db, created)


def test_stale_provisioning_recovery_marks_attempt_failed_and_audits(db):
    created = create(db)
    result = approve(db, created, provision=lambda _org_id: object())
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == created.organisation_id))
    record.status = "provisioning"
    record.provisioning_started_at = datetime.now(UTC) - timedelta(minutes=30)
    db.commit()

    recovered = recover_stale_platform_organisation_provisioning(
        db, actor_user_id=db.info["actor_id"], organisation_id=created.organisation_id,
        reason="Worker interrupted", now=datetime.now(UTC),
    )
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == created.organisation_id))
    event = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "tenant_provisioning_stale_recovered"))
    assert recovered.status == "provisioning_failed"
    assert record.provisioning_error_code == "stale_provisioning_recovered"
    assert record.provisioning_started_at is None
    assert event is not None and event.details["outcome"] == "marked_failed_for_retry"



def test_late_provisioning_result_cannot_overwrite_stale_recovery(db):
    created = create(db)

    def provision_with_interleaved_recovery(organisation_id):
        record = db.scalar(
            select(TenantOnboarding).where(
                TenantOnboarding.organisation_id == organisation_id
            )
        )
        record.provisioning_started_at = datetime.now(UTC) - timedelta(minutes=30)
        db.commit()
        recover_stale_platform_organisation_provisioning(
            db,
            actor_user_id=db.info["actor_id"],
            organisation_id=organisation_id,
            reason="Simulated stale worker recovery",
            now=datetime.now(UTC),
        )

    with pytest.raises(TenantOnboardingConflict, match="superseded"):
        approve(db, created, provision=provision_with_interleaved_recovery)

    record = db.scalar(
        select(TenantOnboarding).where(
            TenantOnboarding.organisation_id == created.organisation_id
        )
    )
    assert record.status == "provisioning_failed"
    assert record.provisioning_error_code == "stale_provisioning_recovered"


def test_stale_provisioning_recovery_rejects_fresh_attempt(db):
    created = create(db)
    approve(db, created)
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == created.organisation_id))
    record.status = "provisioning"
    record.provisioning_started_at = datetime.now(UTC)
    db.commit()
    with pytest.raises(TenantOnboardingConflict, match="not stale yet"):
        recover_stale_platform_organisation_provisioning(
            db, actor_user_id=db.info["actor_id"], organisation_id=created.organisation_id,
            reason="Too early", now=datetime.now(UTC),
        )


def test_provisioning_attempts_are_bounded(db):
    created = create(db)
    approve(db, created, provision=lambda _org_id: (_ for _ in ()).throw(OSError()))
    record = db.scalar(select(TenantOnboarding).where(TenantOnboarding.organisation_id == created.organisation_id))
    record.provisioning_attempts = 5
    db.commit()
    with pytest.raises(TenantOnboardingConflict, match="Maximum provisioning attempts"):
        retry_platform_organisation_provisioning(
            db, actor_user_id=db.info["actor_id"], organisation_id=created.organisation_id,
            reason="retry", provision_workspace=lambda _org_id: object(),
        )
