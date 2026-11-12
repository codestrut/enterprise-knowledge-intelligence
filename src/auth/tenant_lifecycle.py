"""Pure lifecycle and activation guards for Task 06 tenant onboarding.

This module deliberately has no persistence or HTTP dependencies. API/service
code must source predicate values from authoritative server-side records, then
call these guards inside the transaction that performs the state transition.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


class TenantLifecycleStatus(StrEnum):
    REGISTRATION_PENDING = "registration_pending"
    PROVISIONING = "provisioning"
    PROVISIONING_FAILED = "provisioning_failed"
    PENDING_ADMIN = "pending_admin"
    ACTIVE = "active"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


_ALLOWED_TRANSITIONS: dict[TenantLifecycleStatus, frozenset[TenantLifecycleStatus]] = {
    TenantLifecycleStatus.REGISTRATION_PENDING: frozenset(
        {TenantLifecycleStatus.PROVISIONING, TenantLifecycleStatus.REJECTED}
    ),
    TenantLifecycleStatus.PROVISIONING: frozenset(
        {
            TenantLifecycleStatus.PENDING_ADMIN,
            TenantLifecycleStatus.PROVISIONING_FAILED,
            TenantLifecycleStatus.REJECTED,
        }
    ),
    TenantLifecycleStatus.PROVISIONING_FAILED: frozenset(
        {TenantLifecycleStatus.PROVISIONING, TenantLifecycleStatus.REJECTED}
    ),
    TenantLifecycleStatus.PENDING_ADMIN: frozenset(
        {TenantLifecycleStatus.ACTIVE, TenantLifecycleStatus.PROVISIONING_FAILED}
    ),
    TenantLifecycleStatus.ACTIVE: frozenset({TenantLifecycleStatus.SUSPENDED}),
    TenantLifecycleStatus.SUSPENDED: frozenset({TenantLifecycleStatus.ACTIVE}),
    TenantLifecycleStatus.REJECTED: frozenset(),
}


class InvalidTenantTransition(ValueError):
    """Raised when a requested lifecycle transition is not allowed."""


def allowed_transitions(
    current: TenantLifecycleStatus | str,
) -> frozenset[TenantLifecycleStatus]:
    """Return the allowed next states for a known lifecycle state."""
    try:
        state = TenantLifecycleStatus(current)
    except ValueError as exc:
        raise ValueError(f"Unknown tenant lifecycle status: {current!r}") from exc
    return _ALLOWED_TRANSITIONS[state]


def validate_transition(
    current: TenantLifecycleStatus | str,
    target: TenantLifecycleStatus | str,
) -> None:
    """Raise unless target is an explicitly allowed next lifecycle state."""
    try:
        source_state = TenantLifecycleStatus(current)
        target_state = TenantLifecycleStatus(target)
    except ValueError as exc:
        raise ValueError("Unknown tenant lifecycle status.") from exc

    if target_state not in _ALLOWED_TRANSITIONS[source_state]:
        raise InvalidTenantTransition(
            f"Transition from {source_state.value!r} to {target_state.value!r} is not allowed."
        )


@dataclass(frozen=True, slots=True)
class ActivationPredicates:
    """Server-verified facts required before initial tenant activation.

    These values must be derived from trusted persisted records and completed
    operations; request-body claims must never be passed through as proof.
    """

    requester_email_verified: bool = False
    organisational_review_approved: bool = False
    provisioning_completed_and_reconciled: bool = False
    invitation_valid: bool = False
    invitation_single_use: bool = False
    invitation_bound_to_tenant: bool = False
    invitation_bound_to_email: bool = False
    invitation_role_is_initial_admin: bool = False
    initial_admin_identity_verified: bool = False
    membership_can_be_established: bool = False
    required_audit_events_persisted: bool = False


_ACTIVATION_REQUIREMENTS: tuple[tuple[str, str], ...] = (
    ("requester_email_unverified", "requester_email_verified"),
    ("organisational_review_not_approved", "organisational_review_approved"),
    (
        "provisioning_incomplete_or_unreconciled",
        "provisioning_completed_and_reconciled",
    ),
    ("invitation_invalid", "invitation_valid"),
    ("invitation_not_single_use", "invitation_single_use"),
    ("invitation_tenant_mismatch", "invitation_bound_to_tenant"),
    ("invitation_email_mismatch", "invitation_bound_to_email"),
    ("invitation_role_mismatch", "invitation_role_is_initial_admin"),
    ("initial_admin_identity_unverified", "initial_admin_identity_verified"),
    ("membership_cannot_be_established", "membership_can_be_established"),
    ("required_audit_events_missing", "required_audit_events_persisted"),
)


class TenantActivationDenied(ValueError):
    """Raised when one or more activation predicates are not satisfied."""

    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(blockers)
        super().__init__("Tenant activation denied: " + ", ".join(self.blockers))


def activation_blockers(
    current_status: TenantLifecycleStatus | str,
    predicates: ActivationPredicates,
) -> tuple[str, ...]:
    """Return stable blocker codes for the centralized activation decision.

    An already-active tenant is accepted only when every predicate still
    verifies, making a retry idempotent without skipping server-side checks.
    Rejected and suspended tenants cannot pass this initial-activation gate.
    Reactivation requires its own explicit policy/service path.
    """
    try:
        state = TenantLifecycleStatus(current_status)
    except ValueError as exc:
        raise ValueError(f"Unknown tenant lifecycle status: {current_status!r}") from exc

    blockers: list[str] = []
    if state in {TenantLifecycleStatus.REJECTED, TenantLifecycleStatus.SUSPENDED}:
        blockers.append("tenant_rejected_or_suspended")
    elif state not in {TenantLifecycleStatus.PENDING_ADMIN, TenantLifecycleStatus.ACTIVE}:
        blockers.append("tenant_not_pending_initial_admin_activation")

    for blocker, predicate_name in _ACTIVATION_REQUIREMENTS:
        if getattr(predicates, predicate_name) is not True:
            blockers.append(blocker)
    return tuple(blockers)


def validate_activation(
    current_status: TenantLifecycleStatus | str,
    predicates: ActivationPredicates,
) -> None:
    """Raise unless all server-side initial activation predicates are true."""
    blockers = activation_blockers(current_status, predicates)
    if blockers:
        raise TenantActivationDenied(blockers)
