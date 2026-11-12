"""Persistence service for platform-led tenant creation and provisioning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from src.auth.models import AuditEvent, Organisation, TenantOnboarding


MAX_PROVISIONING_ATTEMPTS = 5
DEFAULT_STALE_PROVISIONING_AFTER = timedelta(minutes=15)


class TenantOnboardingConflict(ValueError):
    """The idempotency key or organisation lifecycle conflicts with prior state."""


@dataclass(frozen=True, slots=True)
class TenantCreationResult:
    organisation_id: UUID
    name: str
    slug: str
    status: str
    initial_admin_email: str
    provisioning_attempts: int
    idempotent_replay: bool


def _fingerprint(name: str, slug: str, initial_admin_email: str) -> str:
    body = json.dumps(
        {"name": name, "slug": slug, "initial_admin_email": initial_admin_email},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _result(record: TenantOnboarding, organisation: Organisation, replay: bool) -> TenantCreationResult:
    return TenantCreationResult(
        organisation_id=organisation.id,
        name=organisation.name,
        slug=organisation.slug,
        status=record.status,
        initial_admin_email=record.initial_admin_email,
        provisioning_attempts=record.provisioning_attempts,
        idempotent_replay=replay,
    )


def _record_provisioning_result(
    db: Session,
    *,
    record_id: UUID,
    organisation_id: UUID,
    actor_user_id: UUID,
    expected_attempt: int,
    provision_workspace: Callable[[UUID], object],
) -> TenantCreationResult:
    """Run external provisioning, then finalize only if this attempt is still current.

    The external operation deliberately runs without a database row lock. After it
    returns, a fresh locked read prevents a late result from overwriting a recovery
    or a newer retry.
    """
    initial = db.get(TenantOnboarding, record_id)
    organisation = db.get(Organisation, organisation_id)
    if initial is None or organisation is None:
        raise TenantOnboardingConflict("Tenant onboarding record was not found.")

    failure = False
    try:
        provision_workspace(organisation_id)
    except Exception:
        failure = True

    record = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.id == record_id)
        .with_for_update()
    )
    organisation = db.get(Organisation, organisation_id)
    if record is None or organisation is None:
        db.rollback()
        raise TenantOnboardingConflict("Tenant onboarding record was not found.")
    if record.status != "provisioning" or record.provisioning_attempts != expected_attempt:
        db.rollback()
        raise TenantOnboardingConflict(
            "Provisioning attempt was superseded; its result was not applied."
        )

    if failure:
        record.status = "provisioning_failed"
        record.provisioning_started_at = None
        record.provisioning_error_code = "workspace_provisioning_failed"
        db.add(AuditEvent(
            actor_user_id=actor_user_id,
            organisation_id=organisation_id,
            event_type="tenant_provisioning_failed",
            target_type="organisation",
            target_id=str(organisation_id),
            details={"action": "tenant_provisioning_failed", "outcome": "failed", "reason": "workspace_provisioning_failed", "attempt": expected_attempt},
        ))
        db.commit()
        return _result(record, organisation, False)

    record.status = "pending_admin"
    record.provisioning_started_at = None
    record.provisioning_completed_at = datetime.now(UTC)
    record.provisioning_error_code = None
    db.add(AuditEvent(
        actor_user_id=actor_user_id,
        organisation_id=organisation_id,
        event_type="tenant_provisioning_completed",
        target_type="organisation",
        target_id=str(organisation_id),
        details={"action": "tenant_provisioning_completed", "outcome": "success", "attempt": expected_attempt},
    ))
    db.commit()
    return _result(record, organisation, False)


def create_platform_organisation(
    db: Session,
    *,
    actor_user_id: UUID,
    name: str,
    slug: str,
    initial_admin_email: str,
    idempotency_key: str,
) -> TenantCreationResult:
    """Persist a tenant creation request pending explicit platform approval.

    Creation does not provision external resources or enable access. The separate
    approval operation records the approver and only then starts provisioning.
    """
    if not idempotency_key or len(idempotency_key) > 200 or not idempotency_key.strip():
        raise ValueError("A valid Idempotency-Key header is required.")
    normalized = (name.strip(), slug.strip().lower(), initial_admin_email.strip().lower())
    request_hash = _fingerprint(*normalized)

    existing = db.scalar(
        select(TenantOnboarding).where(
            TenantOnboarding.created_by_user_id == actor_user_id,
            TenantOnboarding.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        organisation = db.get(Organisation, existing.organisation_id)
        if organisation is None:
            raise TenantOnboardingConflict("Idempotency record has no organisation.")
        if existing.request_fingerprint != request_hash:
            raise TenantOnboardingConflict("Idempotency-Key was already used for a different request.")
        db.rollback()
        return _result(existing, organisation, True)

    organisation = Organisation(id=uuid4(), name=normalized[0], slug=normalized[1], is_active=False)
    record = TenantOnboarding(
        organisation=organisation,
        status="registration_pending",
        initial_admin_email=normalized[2],
        idempotency_key=idempotency_key,
        request_fingerprint=request_hash,
        created_by_user_id=actor_user_id,
        provisioning_attempts=0,
    )
    # Persist the parent row before inserting records that reference it.
    # Keep the flush and all dependent inserts in the same transaction.
    db.add(organisation)
    try:
        # Flush the parent first so dependent rows respect SQLite foreign keys.
        # Keep this flush inside the handler so uniqueness errors become conflicts.
        db.flush()
        db.add_all([
            record,
            AuditEvent(
                actor_user_id=actor_user_id,
                organisation_id=organisation.id,
                event_type="tenant_created_pending_approval",
                target_type="organisation",
                target_id=str(organisation.id),
                details={"action": "tenant_created_pending_approval", "outcome": "success"},
            ),
        ])
        db.commit()
    except IntegrityError:
        db.rollback()
        concurrent = db.scalar(
            select(TenantOnboarding).where(
                TenantOnboarding.created_by_user_id == actor_user_id,
                TenantOnboarding.idempotency_key == idempotency_key,
            )
        )
        if concurrent is not None:
            concurrent_org = db.get(Organisation, concurrent.organisation_id)
            if concurrent_org is not None and concurrent.request_fingerprint == request_hash:
                db.rollback()
                return _result(concurrent, concurrent_org, True)
        raise TenantOnboardingConflict("Organisation slug or idempotency key already exists.") from None
    except SQLAlchemyError:
        db.rollback()
        raise
    return _result(record, organisation, False)


def approve_and_provision_platform_organisation(
    db: Session,
    *,
    actor_user_id: UUID,
    organisation_id: UUID,
    approval_reason: str,
    provision_workspace: Callable[[UUID], object],
) -> TenantCreationResult:
    """Record explicit approval, then run retry-safe workspace provisioning."""
    record = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation_id)
        .with_for_update()
    )
    organisation = db.get(Organisation, organisation_id)
    if record is None or organisation is None:
        raise TenantOnboardingConflict("Tenant onboarding record was not found.")
    if record.status == "pending_admin":
        db.rollback()
        return _result(record, organisation, True)
    if record.status != "registration_pending":
        raise TenantOnboardingConflict("Tenant is not awaiting provisioning approval.")

    same_actor = record.created_by_user_id == actor_user_id
    record.status = "provisioning"
    record.provisioning_started_at = datetime.now(UTC)
    record.approved_by_user_id = actor_user_id
    record.provisioning_attempts += 1
    db.add(AuditEvent(
        actor_user_id=actor_user_id,
        organisation_id=organisation_id,
        event_type="tenant_provisioning_started",
        target_type="organisation",
        target_id=str(organisation_id),
        details={
            "action": "tenant_provisioning_started",
            "outcome": "started",
            "approval_reason": approval_reason.strip()[:1000],
            "creator_also_approver": same_actor,
        },
    ))
    db.commit()
    return _record_provisioning_result(
        db,
        record_id=record.id,
        organisation_id=organisation_id,
        actor_user_id=actor_user_id,
        expected_attempt=record.provisioning_attempts,
        provision_workspace=provision_workspace,
    )


def retry_platform_organisation_provisioning(
    db: Session,
    *,
    actor_user_id: UUID,
    organisation_id: UUID,
    reason: str,
    provision_workspace: Callable[[UUID], object],
) -> TenantCreationResult:
    """Retry only a failed tenant provisioning operation, with durable audit state."""
    record = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation_id)
        .with_for_update()
    )
    organisation = db.get(Organisation, organisation_id)
    if record is None or organisation is None:
        raise TenantOnboardingConflict("Tenant onboarding record was not found.")
    if record.status != "provisioning_failed":
        raise TenantOnboardingConflict("Only failed tenant provisioning can be retried.")

    if record.provisioning_attempts >= MAX_PROVISIONING_ATTEMPTS:
        raise TenantOnboardingConflict("Maximum provisioning attempts reached; operator review is required.")
    record.status = "provisioning"
    record.provisioning_started_at = datetime.now(UTC)
    record.provisioning_attempts += 1
    record.provisioning_error_code = None
    db.add(AuditEvent(
        actor_user_id=actor_user_id,
        organisation_id=organisation.id,
        event_type="tenant_provisioning_retried",
        target_type="organisation",
        target_id=str(organisation.id),
        details={
            "action": "tenant_provisioning_retried",
            "outcome": "started",
            "reason": reason.strip()[:1000],
            "attempt": record.provisioning_attempts,
        },
    ))
    db.commit()
    return _record_provisioning_result(
        db,
        record_id=record.id,
        organisation_id=organisation.id,
        actor_user_id=actor_user_id,
        expected_attempt=record.provisioning_attempts,
        provision_workspace=provision_workspace,
    )


def recover_stale_platform_organisation_provisioning(
    db: Session,
    *,
    actor_user_id: UUID,
    organisation_id: UUID,
    reason: str,
    stale_after: timedelta = DEFAULT_STALE_PROVISIONING_AFTER,
    now: datetime | None = None,
) -> TenantCreationResult:
    """Atomically mark a stale in-flight attempt failed so a bounded retry can resume it.

    Recovery does not call external provisioning while holding a database lock. A
    subsequent authorized retry reuses the idempotent workspace provisioner.
    """
    record = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation_id)
        .with_for_update()
    )
    organisation = db.get(Organisation, organisation_id)
    if record is None or organisation is None:
        raise TenantOnboardingConflict("Tenant onboarding record was not found.")
    if record.status != "provisioning" or record.provisioning_started_at is None:
        raise TenantOnboardingConflict("Tenant has no recoverable provisioning attempt.")
    current = now or datetime.now(UTC)
    started = record.provisioning_started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if current - started < stale_after:
        raise TenantOnboardingConflict("Provisioning attempt is not stale yet.")

    record.status = "provisioning_failed"
    record.provisioning_started_at = None
    record.provisioning_error_code = "stale_provisioning_recovered"
    db.add(AuditEvent(
        actor_user_id=actor_user_id,
        organisation_id=organisation_id,
        event_type="tenant_provisioning_stale_recovered",
        target_type="organisation",
        target_id=str(organisation_id),
        details={
            "action": "tenant_provisioning_stale_recovered",
            "outcome": "marked_failed_for_retry",
            "reason": reason.strip()[:1000],
            "attempt": record.provisioning_attempts,
        },
    ))
    db.commit()
    return _result(record, organisation, False)
