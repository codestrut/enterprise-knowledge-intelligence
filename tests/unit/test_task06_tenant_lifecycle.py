"""Tests for the Task 06 lifecycle and initial-admin activation gates."""

import pytest

from src.auth.tenant_lifecycle import (
    ActivationPredicates,
    InvalidTenantTransition,
    TenantActivationDenied,
    TenantLifecycleStatus as Status,
    activation_blockers,
    allowed_transitions,
    validate_activation,
    validate_transition,
)


def complete_predicates() -> ActivationPredicates:
    return ActivationPredicates(
        requester_email_verified=True,
        organisational_review_approved=True,
        provisioning_completed_and_reconciled=True,
        invitation_valid=True,
        invitation_single_use=True,
        invitation_bound_to_tenant=True,
        invitation_bound_to_email=True,
        invitation_role_is_initial_admin=True,
        initial_admin_identity_verified=True,
        membership_can_be_established=True,
        required_audit_events_persisted=True,
    )


def test_approved_lifecycle_transitions_are_explicit():
    assert allowed_transitions(Status.REGISTRATION_PENDING) == frozenset(
        {Status.PROVISIONING, Status.REJECTED}
    )
    assert allowed_transitions(Status.PROVISIONING_FAILED) == frozenset(
        {Status.PROVISIONING, Status.REJECTED}
    )
    assert allowed_transitions(Status.ACTIVE) == frozenset({Status.SUSPENDED})
    assert allowed_transitions(Status.REJECTED) == frozenset()


def test_valid_transition_accepts_enum_or_contract_string():
    validate_transition("registration_pending", Status.PROVISIONING)
    validate_transition(Status.ACTIVE, "suspended")


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (Status.REGISTRATION_PENDING, Status.ACTIVE),
        (Status.PROVISIONING, Status.ACTIVE),
        (Status.PROVISIONING_FAILED, Status.PENDING_ADMIN),
        (Status.PENDING_ADMIN, Status.SUSPENDED),
        (Status.REJECTED, Status.PROVISIONING),
        (Status.SUSPENDED, Status.PENDING_ADMIN),
    ],
)
def test_invalid_lifecycle_transitions_are_rejected(current, target):
    with pytest.raises(InvalidTenantTransition):
        validate_transition(current, target)


def test_activation_allowed_only_when_all_server_side_predicates_pass():
    validate_activation(Status.PENDING_ADMIN, complete_predicates())


def test_activation_reports_each_missing_predicate_without_mutating_state():
    blockers = activation_blockers(Status.PENDING_ADMIN, ActivationPredicates())
    assert "requester_email_unverified" in blockers
    assert "organisational_review_not_approved" in blockers
    assert "provisioning_incomplete_or_unreconciled" in blockers
    assert "invitation_invalid" in blockers
    assert "initial_admin_identity_unverified" in blockers
    assert "required_audit_events_missing" in blockers

    with pytest.raises(TenantActivationDenied) as error:
        validate_activation(Status.PENDING_ADMIN, ActivationPredicates())
    assert error.value.blockers == blockers


@pytest.mark.parametrize("status", [Status.REJECTED, Status.SUSPENDED])
def test_rejected_or_suspended_tenant_cannot_pass_activation_gate(status):
    blockers = activation_blockers(status, complete_predicates())
    assert blockers == ("tenant_rejected_or_suspended",)


def test_activation_cannot_bypass_pending_admin_state():
    blockers = activation_blockers(Status.PROVISIONING, complete_predicates())
    assert blockers == ("tenant_not_pending_initial_admin_activation",)


def test_activation_retry_is_idempotently_allowed_only_with_all_predicates():
    validate_activation(Status.ACTIVE, complete_predicates())
    blockers = activation_blockers(Status.ACTIVE, ActivationPredicates())
    assert "tenant_not_pending_initial_admin_activation" not in blockers
    assert "invitation_invalid" in blockers


def test_untrusted_truthy_values_do_not_satisfy_predicates():
    # Service code should supply real booleans from authoritative state, not
    # unvalidated strings or arbitrary truthy values.
    values = {field: True for field in ActivationPredicates.__dataclass_fields__}
    values["requester_email_verified"] = "true"
    predicates = ActivationPredicates(**values)  # type: ignore[arg-type]
    blockers = activation_blockers(Status.PENDING_ADMIN, predicates)
    assert "requester_email_unverified" in blockers
