"""Task 06 request contracts.

These Pydantic models define request validation only. They deliberately do not
create persistence, expose endpoints, or imply that the Task 05.3/G1 migration
gates have passed. Route handlers must still enforce authentication,
authorization, idempotency, lifecycle transitions, and server-side tenant scope.
"""

from __future__ import annotations

import re
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

from src.auth.permissions import Role, PlatformRole


_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Task06Request(BaseModel):
    """Strict base class for Task 06 request bodies."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _normalise_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Value must not be empty.")
    return value


def _normalise_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(value):
        raise ValueError("A valid email address is required.")
    return value


def _normalise_slug(value: str) -> str:
    value = value.strip().lower()
    if not _SLUG_PATTERN.fullmatch(value):
        raise ValueError(
            "Slug must contain lowercase letters, digits, and single hyphens only."
        )
    return value


class TenantRegistrationRequestCreate(Task06Request):
    """Public self-service registration request; does not create an active tenant."""

    organisation_name: Annotated[str, Field(min_length=1, max_length=200)]
    requested_slug: Annotated[str, Field(min_length=1, max_length=120)]
    requester_name: Annotated[str | None, Field(max_length=200)] = None
    requester_email: Annotated[str, Field(min_length=3, max_length=320)]
    purpose: Annotated[str, Field(min_length=1, max_length=2000)]
    terms_version: Annotated[str | None, Field(max_length=80)] = None

    @field_validator("organisation_name", "purpose", mode="before")
    @classmethod
    def trim_required_text(cls, value: object) -> object:
        if isinstance(value, str):
            return _normalise_name(value)
        return value

    @field_validator("requester_name", mode="before")
    @classmethod
    def trim_optional_name(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return _normalise_name(value)
        return value

    @field_validator("requester_email")
    @classmethod
    def normalise_requester_email(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("requested_slug")
    @classmethod
    def normalise_requested_slug(cls, value: str) -> str:
        return _normalise_slug(value)


class VerifyTenantRegistrationRequest(Task06Request):
    verification_token: Annotated[SecretStr, Field(min_length=1, max_length=512)]


class ReviewTenantRegistrationRequest(Task06Request):
    decision_reason: Annotated[str | None, Field(max_length=1000)] = None


class RejectTenantRegistrationRequest(Task06Request):
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]
    reviewer_note: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("reason_code")
    @classmethod
    def trim_reason_code(cls, value: str) -> str:
        return _normalise_name(value)


class PlatformOrganisationCreateRequest(Task06Request):
    """Platform-led creation starts provisioning; it does not activate a tenant."""

    name: Annotated[str, Field(min_length=1, max_length=200)]
    slug: Annotated[str, Field(min_length=1, max_length=120)]
    initial_admin_email: Annotated[str, Field(min_length=3, max_length=320)]

    @field_validator("name", mode="before")
    @classmethod
    def trim_name(cls, value: object) -> object:
        if isinstance(value, str):
            return _normalise_name(value)
        return value

    @field_validator("slug")
    @classmethod
    def normalise_slug(cls, value: str) -> str:
        return _normalise_slug(value)

    @field_validator("initial_admin_email")
    @classmethod
    def normalise_initial_admin_email(cls, value: str) -> str:
        return _normalise_email(value)


class ApprovePlatformOrganisationProvisioningRequest(Task06Request):
    """Explicit platform review approval before tenant resource provisioning."""

    approval_reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("approval_reason", mode="before")
    @classmethod
    def trim_approval_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return _normalise_name(value)
        return value


class ApproveOrganisationActivationRequest(Task06Request):
    approval_reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("approval_reason", mode="before")
    @classmethod
    def trim_approval_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return _normalise_name(value)
        return value


class SuspendOrganisationRequest(Task06Request):
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]
    note: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("reason_code")
    @classmethod
    def trim_reason_code(cls, value: str) -> str:
        return _normalise_name(value)


class OrganisationInvitationCreateRequest(Task06Request):
    recipient_email: Annotated[str, Field(min_length=3, max_length=320)]
    role: Role
    message: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("recipient_email")
    @classmethod
    def normalise_recipient_email(cls, value: str) -> str:
        return _normalise_email(value)


class AcceptOrganisationInvitationRequest(Task06Request):
    token: Annotated[SecretStr, Field(min_length=1, max_length=512)]


class ProvisioningRetryRequest(Task06Request):
    operation_id: Annotated[str | None, Field(min_length=1, max_length=120)] = None
    retry_scope: Annotated[str | None, Field(min_length=1, max_length=80)] = None
    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return _normalise_name(value)

    @field_validator("operation_id", "retry_scope", mode="before")
    @classmethod
    def trim_optional_identifiers(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            return _normalise_name(value)
        return value

    @model_validator(mode="after")
    def require_retry_selector(self) -> Self:
        if not self.operation_id and not self.retry_scope:
            raise ValueError("Provide operation_id or retry_scope.")
        return self


class PlatformRoleAssignmentRequest(Task06Request):
    """Grant one built-in platform role to a user."""

    user_id: UUID
    role: PlatformRole


class ProvisioningRecoveryRequest(Task06Request):
    """Reason required to recover a stale in-flight provisioning attempt."""

    reason: Annotated[str, Field(min_length=1, max_length=1000)]

    @field_validator("reason", mode="before")
    @classmethod
    def trim_reason(cls, value: object) -> object:
        if isinstance(value, str):
            return _normalise_name(value)
        return value
