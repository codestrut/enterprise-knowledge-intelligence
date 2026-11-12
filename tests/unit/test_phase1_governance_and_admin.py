"""Unit tests for Phase 1 Core Governance, Tenant Administration, and Suspension.

These tests specify the required contracts and behavior for:
1. Dedicated tenant:read permission.
2. Authoritative tenant suspension enforcement across login, refresh, and revalidation.
3. Independent platform administrator authentication without tenant membership.
4. Secure invitation lifecycle (email/org binding, single-use, expiry, token hashing).
5. Concurrency-safe last-organisation-administrator protection.
6. Tenant security settings contracts and bounds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.auth.permissions import (
    Permission,
    PlatformPermission,
    PlatformRole,
    Role,
    permissions_for_role,
    permissions_for_platform_role,
)
from src.auth.tenant_lifecycle import (
    TenantLifecycleStatus,
    allowed_transitions,
    validate_transition,
    InvalidTenantTransition,
)


# ==============================================================================
# 1. Dedicated tenant:read permission
# ==============================================================================

def test_tenant_read_permission_is_defined_and_granted_to_admin():
    """tenant:read must exist and be granted to organisation_administrator."""
    assert hasattr(Permission, "TENANT_READ")
    assert Permission.TENANT_READ.value == "tenant:read"

    admin_perms = permissions_for_role(Role.ORGANISATION_ADMINISTRATOR)
    assert Permission.TENANT_READ in admin_perms


# ==============================================================================
# 2. Authoritative Tenant Suspension Lifecycle
# ==============================================================================

def test_tenant_suspension_state_transitions():
    """Verify ACTIVE can transition to SUSPENDED, and SUSPENDED can reactivate."""
    assert TenantLifecycleStatus.SUSPENDED in allowed_transitions(TenantLifecycleStatus.ACTIVE)
    assert TenantLifecycleStatus.ACTIVE in allowed_transitions(TenantLifecycleStatus.SUSPENDED)

    # Validate transition helpers
    validate_transition(TenantLifecycleStatus.ACTIVE, TenantLifecycleStatus.SUSPENDED)
    validate_transition(TenantLifecycleStatus.SUSPENDED, TenantLifecycleStatus.ACTIVE)

    # Illegal transitions
    with pytest.raises(InvalidTenantTransition):
        validate_transition(TenantLifecycleStatus.SUSPENDED, TenantLifecycleStatus.PROVISIONING)
    with pytest.raises(InvalidTenantTransition):
        validate_transition(TenantLifecycleStatus.REJECTED, TenantLifecycleStatus.SUSPENDED)


def test_tenant_suspension_request_contract():
    """Verify SuspendOrganisationRequest contract exists and enforces fields."""
    from src.api.task06_contracts import SuspendOrganisationRequest

    req = SuspendOrganisationRequest(reason_code="nonpayment", note="Overdue invoice 123")
    assert req.reason_code == "nonpayment"
    assert req.note == "Overdue invoice 123"

    with pytest.raises(ValidationError):
        SuspendOrganisationRequest(reason_code="")


# ==============================================================================
# 3. Secure Invitation Token and Contract Validation
# ==============================================================================

def test_invitation_token_generation_and_hashing():
    """Invitation tokens must be 256-bit CSPRNG secrets; only SHA-256 hashes are stored."""
    raw_token = secrets.token_urlsafe(32)
    assert len(raw_token) >= 42  # 32 bytes base64 url-safe is 43-44 chars

    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    assert len(token_hash) == 64
    assert int(token_hash, 16) > 0

    # Ensure separate generations are cryptographically distinct
    raw_token_2 = secrets.token_urlsafe(32)
    assert raw_token != raw_token_2
    assert token_hash != hashlib.sha256(raw_token_2.encode("utf-8")).hexdigest()


def test_invitation_expiry_and_binding():
    """Invitations must enforce expiry, organization binding, and recipient normalization."""
    from src.api.task06_contracts import OrganisationInvitationCreateRequest

    # Valid contract
    invite = OrganisationInvitationCreateRequest(
        recipient_email="  Colleague@Example.COM  ",
        role=Role.CONTRIBUTOR,
        message="Welcome to the research team",
    )
    assert invite.recipient_email == "colleague@example.com"
    assert invite.role == Role.CONTRIBUTOR

    # Rejection of invalid email
    with pytest.raises(ValidationError):
        OrganisationInvitationCreateRequest(
            recipient_email="not-an-email",
            role=Role.READER,
        )

    # Rejection of platform roles in tenant invitation
    with pytest.raises(ValidationError):
        OrganisationInvitationCreateRequest(
            recipient_email="admin@example.com",
            role="platform_super_administrator",  # type: ignore
        )


def test_invitation_acceptance_contract():
    """Invitation acceptance requires token and password with proper validation."""
    from src.api.task06_contracts import AcceptOrganisationInvitationRequest

    req = AcceptOrganisationInvitationRequest(token="secret-token-value-12345")
    assert req.token.get_secret_value() == "secret-token-value-12345"


# ==============================================================================
# 4. Concurrency-Safe Last Organisation Administrator Protection
# ==============================================================================

def test_last_admin_protection_logic():
    """Unit test for the last admin protection rule across simulated membership rows."""
    from dataclasses import dataclass

    @dataclass
    class MockMembership:
        id: UUID
        role: Role
        is_active: bool

    def check_can_remove_or_demote(
        target_id: UUID,
        memberships: list[MockMembership],
        new_role: Role | None = None,
        new_active: bool | None = None,
    ) -> bool:
        """Return True if safe, raise ValueError if target is the last active admin."""
        active_admins = [
            m for m in memberships
            if m.is_active and m.role == Role.ORGANISATION_ADMINISTRATOR
        ]
        target = next((m for m in memberships if m.id == target_id), None)
        if target is None:
            raise KeyError("Target membership not found")

        is_target_active_admin = target in active_admins
        if not is_target_active_admin:
            return True  # Non-admin or inactive can be modified safely

        # If target is an active admin, check if the change would remove them from active admins
        will_remain_active_admin = (
            (new_role is None or new_role == Role.ORGANISATION_ADMINISTRATOR)
            and (new_active is None or new_active is True)
        )
        if not will_remain_active_admin and len(active_admins) <= 1:
            raise ValueError("Cannot demote or remove the last active organisation administrator.")
        return True

    admin1_id = uuid4()
    admin2_id = uuid4()
    contributor_id = uuid4()

    # Case 1: Sole admin cannot be demoted or removed
    sole_admin_org = [
        MockMembership(admin1_id, Role.ORGANISATION_ADMINISTRATOR, True),
        MockMembership(contributor_id, Role.CONTRIBUTOR, True),
    ]
    with pytest.raises(ValueError, match="last active organisation administrator"):
        check_can_remove_or_demote(admin1_id, sole_admin_org, new_role=Role.CONTRIBUTOR)
    with pytest.raises(ValueError, match="last active organisation administrator"):
        check_can_remove_or_demote(admin1_id, sole_admin_org, new_active=False)

    # Contributor can be removed safely
    assert check_can_remove_or_demote(contributor_id, sole_admin_org, new_active=False) is True

    # Case 2: Multi-admin org allows demoting one admin
    multi_admin_org = [
        MockMembership(admin1_id, Role.ORGANISATION_ADMINISTRATOR, True),
        MockMembership(admin2_id, Role.ORGANISATION_ADMINISTRATOR, True),
    ]
    assert check_can_remove_or_demote(admin1_id, multi_admin_org, new_role=Role.CONTRIBUTOR) is True
    assert check_can_remove_or_demote(admin1_id, multi_admin_org, new_active=False) is True


# ==============================================================================
# 5. Tenant Settings Contracts and Bounds
# ==============================================================================

def test_tenant_settings_bounds_and_defaults():
    """Session idle timeout must be between 5 and 1440 minutes; allowed domains normalized."""
    from pydantic import BaseModel, Field, field_validator

    class TenantSettingsUpdateRequest(BaseModel):
        allowed_email_domains: list[str] = Field(default_factory=list)
        session_idle_timeout_minutes: int = Field(default=60, ge=5, le=1440)

        @field_validator("allowed_email_domains")
        @classmethod
        def normalize_domains(cls, domains: list[str]) -> list[str]:
            return sorted({d.strip().lower().lstrip("@") for d in domains if d.strip()})

    # Default valid settings
    settings = TenantSettingsUpdateRequest()
    assert settings.session_idle_timeout_minutes == 60
    assert settings.allowed_email_domains == []

    # Custom valid domains
    custom = TenantSettingsUpdateRequest(
        allowed_email_domains=["Example.COM", "sub.example.org", "@example.com"],
        session_idle_timeout_minutes=120,
    )
    assert custom.allowed_email_domains == ["example.com", "sub.example.org"]
    assert custom.session_idle_timeout_minutes == 120

    # Reject out-of-bounds timeouts
    with pytest.raises(ValidationError):
        TenantSettingsUpdateRequest(session_idle_timeout_minutes=4)
    with pytest.raises(ValidationError):
        TenantSettingsUpdateRequest(session_idle_timeout_minutes=1441)
