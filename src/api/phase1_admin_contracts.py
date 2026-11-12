"""Pydantic request and response contracts for Phase 1 Core Admin and Governance."""

from __future__ import annotations

import re
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from src.auth.permissions import Role, PlatformRole


_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AdminContractBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _normalise_text(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Field must not be empty.")
    return value


def _normalise_email(value: str) -> str:
    value = value.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(value):
        raise ValueError("A valid email address is required.")
    return value


# --- Tenant Admin Contracts ---------------------------------------------------

class TenantOverviewResponse(AdminContractBase):
    organisation_id: UUID
    organisation_name: str
    document_count: int
    chunk_count: int
    failed_document_count: int
    member_count: int


class TenantMemberView(AdminContractBase):
    id: UUID
    user_id: UUID
    email: str
    role: str
    is_active: bool
    created_at: str


class TenantMemberListResponse(AdminContractBase):
    count: int
    members: list[TenantMemberView]


class TenantMemberInviteRequest(AdminContractBase):
    recipient_email: Annotated[str, Field(min_length=3, max_length=320)]
    role: Role
    message: Annotated[str | None, Field(max_length=1000)] = None

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalise_email(value)


class TenantMemberInviteResponse(AdminContractBase):
    id: UUID
    recipient_email: str
    role: str
    # Present only when an operator explicitly enables development token exposure.
    invitation_token: str | None = None
    expires_at: str


class TenantPendingInvitationView(AdminContractBase):
    id: UUID
    recipient_email: str
    role: str
    invited_by_email: str
    expires_at: str
    created_at: str


class TenantPendingInvitationListResponse(AdminContractBase):
    count: int
    invitations: list[TenantPendingInvitationView]


class AcceptInvitationRequest(AdminContractBase):
    token: Annotated[SecretStr, Field(min_length=1, max_length=512)]
    password: Annotated[SecretStr, Field(min_length=15, max_length=128)]


class TenantMemberUpdateRequest(AdminContractBase):
    role: Role | None = None
    is_active: bool | None = None


class TenantSettingsView(AdminContractBase):
    organisation_id: UUID
    allowed_email_domains: list[str]
    session_idle_timeout_minutes: int


class TenantSettingsUpdateRequest(AdminContractBase):
    allowed_email_domains: list[str] = Field(default_factory=list)
    session_idle_timeout_minutes: int = Field(default=60, ge=5, le=1440)

    @field_validator("allowed_email_domains")
    @classmethod
    def normalize_domains(cls, domains: list[str]) -> list[str]:
        return sorted({d.strip().lower().lstrip("@") for d in domains if d.strip()})


# --- Platform Admin Contracts -------------------------------------------------

class TenantSuspendRequest(AdminContractBase):
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]
    note: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("reason_code")
    @classmethod
    def trim_reason_code(cls, value: str) -> str:
        return _normalise_text(value)


class TenantReactivateRequest(AdminContractBase):
    reason_code: Annotated[str, Field(min_length=1, max_length=80)]
    note: Annotated[str | None, Field(max_length=2000)] = None

    @field_validator("reason_code")
    @classmethod
    def trim_reason_code(cls, value: str) -> str:
        return _normalise_text(value)


class PlatformOverviewResponse(AdminContractBase):
    total_tenants: int
    active_tenants: int
    pending_tenants: int
    provisioning_tenants: int
    failed_tenants: int
    suspended_tenants: int
    total_documents: int
    total_chunks: int


class PlatformRoleHolderView(AdminContractBase):
    id: UUID
    user_id: UUID
    email: str
    role: str
    assigned_at: str


class PlatformRoleHolderListResponse(AdminContractBase):
    count: int
    assignments: list[PlatformRoleHolderView]
