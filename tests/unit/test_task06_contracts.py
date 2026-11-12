"""Focused validation tests for the Task 06 request-contract foundation."""

import pytest
from pydantic import ValidationError

from src.api.task06_contracts import (
    AcceptOrganisationInvitationRequest,
    ApprovePlatformOrganisationProvisioningRequest,
    OrganisationInvitationCreateRequest,
    PlatformOrganisationCreateRequest,
    ProvisioningRetryRequest,
    TenantRegistrationRequestCreate,
    VerifyTenantRegistrationRequest,
)
from src.auth.permissions import Role


def test_registration_request_normalises_public_fields():
    request = TenantRegistrationRequestCreate(
        organisation_name="  Example Organisation  ",
        requested_slug=" Example-Org ",
        requester_name="  A Person ",
        requester_email=" OWNER@EXAMPLE.ORG ",
        purpose="  Organisational knowledge workspace ",
        terms_version="v1",
    )

    assert request.organisation_name == "Example Organisation"
    assert request.requested_slug == "example-org"
    assert request.requester_name == "A Person"
    assert request.requester_email == "owner@example.org"
    assert request.purpose == "Organisational knowledge workspace"


@pytest.mark.parametrize("slug", ["", "-starts-hyphen", "ends-hyphen-", "two--hyphens", "has space", "under_score", "dot.name"])
def test_registration_rejects_invalid_slug(slug):
    with pytest.raises(ValidationError):
        TenantRegistrationRequestCreate(
            organisation_name="Example",
            requested_slug=slug,
            requester_email="owner@example.org",
            purpose="Need a knowledge workspace",
        )


def test_registration_rejects_bad_email_and_blank_purpose():
    base = {
        "organisation_name": "Example",
        "requested_slug": "example",
        "requester_email": "not-an-email",
        "purpose": "A purpose",
    }
    with pytest.raises(ValidationError):
        TenantRegistrationRequestCreate(**base)

    base["requester_email"] = "owner@example.org"
    base["purpose"] = "   "
    with pytest.raises(ValidationError):
        TenantRegistrationRequestCreate(**base)


def test_request_models_forbid_uncontracted_fields():
    with pytest.raises(ValidationError):
        PlatformOrganisationCreateRequest(
            name="Example",
            slug="example",
            initial_admin_email="owner@example.org",
            is_active=True,
        )


def test_platform_create_normalises_and_does_not_accept_activation_claims():
    request = PlatformOrganisationCreateRequest(
        name=" Example ",
        slug="EXAMPLE-ORG",
        initial_admin_email=" Owner@Example.org ",
    )
    assert request.name == "Example"
    assert request.slug == "example-org"
    assert request.initial_admin_email == "owner@example.org"
    assert "is_active" not in request.model_dump()


def test_verification_token_is_secret_and_required():
    request = VerifyTenantRegistrationRequest(verification_token="not-echoed-token")
    assert request.verification_token.get_secret_value() == "not-echoed-token"
    assert "not-echoed-token" not in request.model_dump_json()

    with pytest.raises(ValidationError):
        VerifyTenantRegistrationRequest(verification_token="")


def test_invitation_only_accepts_tenant_roles_and_normalises_recipient():
    request = OrganisationInvitationCreateRequest(
        recipient_email=" NEW.USER@EXAMPLE.ORG ",
        role=Role.READER,
    )
    assert request.recipient_email == "new.user@example.org"
    assert request.role is Role.READER

    with pytest.raises(ValidationError):
        OrganisationInvitationCreateRequest(
            recipient_email="user@example.org",
            role="platform_administrator",
        )


def test_invitation_token_is_secret():
    request = AcceptOrganisationInvitationRequest(token="single-use-token")
    assert "single-use-token" not in request.model_dump_json()


def test_provisioning_retry_requires_a_selector():
    with pytest.raises(ValidationError):
        ProvisioningRetryRequest(reason="Retry after reviewing the failure")

    request = ProvisioningRetryRequest(
        operation_id="op-123",
        reason="Retry after reviewing the failure",
    )
    assert request.operation_id == "op-123"


def test_platform_provisioning_approval_requires_nonblank_reason():
    request = ApprovePlatformOrganisationProvisioningRequest(approval_reason="  Reviewed by platform  ")
    assert request.approval_reason == "Reviewed by platform"
    with pytest.raises(ValidationError):
        ApprovePlatformOrganisationProvisioningRequest(approval_reason="   ")
