"""SQLAlchemy identity and organisation membership models."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from src.auth.permissions import Permission, Role, PlatformRole, permissions_for_role, permissions_for_platform_role


class Base(DeclarativeBase):
    """Metadata root for the separately managed identity database."""


class Timestamped:
    """Common timezone-aware timestamps for identity records."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Organisation(Timestamped, Base):
    __tablename__ = "organisations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organisations_slug"),
        CheckConstraint("length(trim(name)) > 0", name="ck_organisations_name_nonempty"),
        CheckConstraint("slug = lower(trim(slug))", name="ck_organisations_slug_normalized"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    memberships: Mapped[list["OrganisationMembership"]] = relationship(
        back_populates="organisation"
    )

    @validates("name")
    def normalize_name(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Organisation name must not be empty.")
        return value.strip()

    @validates("slug")
    def normalize_slug(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Organisation slug must not be empty.")
        return value.strip().lower()

    def __repr__(self) -> str:
        return f"Organisation(id={self.id!r})"


class User(Timestamped, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        CheckConstraint("email = lower(trim(email))", name="ck_users_email_normalized"),
        CheckConstraint("length(email) > 0", name="ck_users_email_nonempty"),
        CheckConstraint(
            "password_hash LIKE '$argon2id$%'",
            name="ck_users_password_hash_argon2id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_platform_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    memberships: Mapped[list["OrganisationMembership"]] = relationship(
        back_populates="user"
    )

    @validates("email")
    def normalize_email(self, _key: str, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("Email identity must be text.")
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Email identity must not be empty.")
        return normalized

    @validates("password_hash")
    def require_argon2id_password_hash(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.startswith("$argon2id$"):
            raise ValueError("Only an Argon2id password hash may be stored.")
        return value

    def __repr__(self) -> str:
        # Keep both identity details and password material out of incidental logs.
        return f"User(id={self.id!r})"


class OrganisationMembership(Timestamped, Base):
    __tablename__ = "organisation_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organisation_id", "user_id", name="uq_membership_organisation_user"
        ),
        UniqueConstraint("id", "user_id", name="uq_membership_id_user"),
        Index("ix_membership_user_organisation", "user_id", "organisation_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    role: Mapped[Role] = mapped_column(
        SqlEnum(
            Role,
            name="organisation_membership_role",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
            values_callable=lambda roles: [role.value for role in roles],
            length=40,
        ),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    organisation: Mapped[Organisation] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    @property
    def permissions(self) -> frozenset[Permission]:
        """Resolve the stored role via the shared permission catalog."""
        return permissions_for_role(self.role)

    def __repr__(self) -> str:
        return f"OrganisationMembership(id={self.id!r}, role={self.role.value!r})"


class TenantOnboarding(Timestamped, Base):
    """Durable platform-led tenant provisioning state and idempotency record."""

    __tablename__ = "tenant_onboarding"
    __table_args__ = (
        UniqueConstraint("organisation_id", name="uq_tenant_onboarding_organisation"),
        UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_tenant_onboarding_creator_idempotency"),
        CheckConstraint(
            "status IN ('registration_pending', 'provisioning', 'provisioning_failed', 'pending_admin', 'active', 'suspended', 'rejected')",
            name="ck_tenant_onboarding_status",
        ),
        CheckConstraint("length(trim(initial_admin_email)) > 0", name="ck_tenant_onboarding_admin_email_nonempty"),
        CheckConstraint("provisioning_attempts >= 0", name="ck_tenant_onboarding_attempts_nonnegative"),
        Index("ix_tenant_onboarding_status_created", "status", "created_at"),
        UniqueConstraint("initial_admin_invitation_id", name="uq_tenant_onboarding_initial_invitation"),
        ForeignKeyConstraint(
            ["organisation_id", "initial_admin_invitation_id"],
            ["organisation_invitations.organisation_id", "organisation_invitations.id"],
            name="fk_tenant_onboarding_initial_invitation_same_org",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "initial_admin_invitation_accepted_at IS NULL OR initial_admin_invitation_id IS NOT NULL",
            name="ck_tenant_onboarding_acceptance_needs_invitation",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="registration_pending", server_default="registration_pending")
    initial_admin_email: Mapped[str] = mapped_column(String(320), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    approved_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    provisioning_attempts: Mapped[int] = mapped_column(
        nullable=False, default=0, server_default="0"
    )
    provisioning_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provisioning_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provisioning_error_code: Mapped[str | None] = mapped_column(String(100))
    initial_admin_invitation_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    initial_admin_invitation_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    organisation: Mapped[Organisation] = relationship()

    @validates("initial_admin_email")
    def normalize_initial_admin_email(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Initial administrator email must not be empty.")
        return value.strip().lower()


class PlatformRoleAssignment(Timestamped, Base):
    """Explicit user-scoped platform role assignment with auditable grantor."""

    __tablename__ = "platform_role_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_platform_role_assignment_user_role"),
        CheckConstraint(
            "role IN ('platform_super_administrator', 'platform_tenant_creator', 'platform_tenant_approver', 'platform_provisioning_operator')",
            name="ck_platform_role_assignment_role",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    role: Mapped[PlatformRole] = mapped_column(String(48), nullable=False)
    assigned_by_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)

    @property
    def permissions(self):
        return permissions_for_platform_role(self.role)


class RefreshSessionRecord(Base):
    """Hashed, rotating refresh-session state for one scoped membership."""

    __tablename__ = "auth_refresh_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_auth_refresh_sessions_token_hash"),
        ForeignKeyConstraint(
            ["membership_id", "user_id"],
            ["organisation_memberships.id", "organisation_memberships.user_id"],
            name="fk_auth_refresh_sessions_membership_user",
            ondelete="RESTRICT",
        ),
        Index("ix_auth_refresh_sessions_user_id", "user_id"),
        Index("ix_auth_refresh_sessions_family_id", "family_id"),
        Index("ix_auth_refresh_sessions_expires_at", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisation_memberships.id", ondelete="RESTRICT"),
        nullable=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    family_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    family_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rotation_key_hash: Mapped[str | None] = mapped_column(String(64))
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("auth_refresh_sessions.id", ondelete="RESTRICT")
    )

    def __repr__(self) -> str:
        return f"RefreshSessionRecord(id={self.id!r})"


class AuditEvent(Base):
    """Append-only metadata for security-sensitive account/session actions."""

    __tablename__ = "auth_audit_events"
    __table_args__ = (
        Index("ix_auth_audit_events_actor_time", "actor_user_id", "occurred_at"),
        Index("ix_auth_audit_events_event_time", "event_type", "occurred_at"),
        Index("ix_auth_audit_events_organisation_time", "organisation_id", "occurred_at"),
        CheckConstraint("length(event_type) > 0", name="ck_auth_audit_event_type_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    organisation_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisations.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(80))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    details: Mapped[dict[str, str | int | bool | None]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    def __repr__(self) -> str:
        return f"AuditEvent(id={self.id!r}, event_type={self.event_type!r})"


class OrganisationInvitation(Timestamped, Base):
    """Secure, single-use tenant membership invitation."""

    __tablename__ = "organisation_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_organisation_invitations_token_hash"),
        CheckConstraint("length(trim(recipient_email)) > 0", name="ck_invitations_recipient_nonempty"),
        CheckConstraint("recipient_email = lower(trim(recipient_email))", name="ck_invitations_recipient_normalized"),
        CheckConstraint("role IN ('organisation_administrator', 'contributor', 'reader')", name="ck_invitations_role_valid"),
        Index("ix_organisation_invitations_org", "organisation_id"),
        Index("ix_organisation_invitations_email", "recipient_email"),
        UniqueConstraint("organisation_id", "id", name="uq_organisation_invitations_org_id"),
        ForeignKeyConstraint(
            ["organisation_id", "superseded_by_id"],
            ["organisation_invitations.organisation_id", "organisation_invitations.id"],
            name="fk_invitations_superseded_same_org",
            ondelete="RESTRICT",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("purpose IN ('initial_admin', 'member')", name="ck_invitations_purpose_valid"),
        CheckConstraint(
            "purpose <> 'initial_admin' OR role = 'organisation_administrator'",
            name="ck_invitations_initial_admin_role",
        ),
        CheckConstraint(
            "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
            name="ck_invitations_not_accepted_and_revoked",
        ),
        CheckConstraint(
            "(accepted_at IS NULL) = (accepted_by_user_id IS NULL)",
            name="ck_invitations_acceptance_complete",
        ),
        CheckConstraint(
            "(revoked_at IS NULL) = (revocation_reason IS NULL)",
            name="ck_invitations_revocation_complete",
        ),
        CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN "
            "('superseded', 'revoked_by_admin', 'tenant_suspended', 'tenant_rejected', 'expired')",
            name="ck_invitations_revocation_reason_valid",
        ),
        CheckConstraint(
            "revoked_by_user_id IS NULL OR revoked_at IS NOT NULL",
            name="ck_invitations_revoker_requires_revocation",
        ),
        CheckConstraint(
            "(superseded_by_id IS NULL AND (revocation_reason IS NULL OR revocation_reason <> 'superseded')) "
            "OR (superseded_by_id IS NOT NULL AND revocation_reason = 'superseded' AND superseded_by_id <> id)",
            name="ck_invitations_supersession_pair",
        ),
        Index(
            "uq_org_invitations_one_open_per_recipient",
            "organisation_id",
            "recipient_email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
            sqlite_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
        Index(
            "uq_org_invitations_one_current_initial_admin",
            "organisation_id",
            unique=True,
            postgresql_where=text("purpose = 'initial_admin' AND revoked_at IS NULL"),
            sqlite_where=text("purpose = 'initial_admin' AND revoked_at IS NULL"),
        ),
        Index("ix_org_invitations_recipient_created", "organisation_id", "recipient_email", "created_at"),
        Index(
            "ix_org_invitations_open_expiry",
            "expires_at",
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
            sqlite_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    organisation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invited_by_user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purpose: Mapped[str] = mapped_column(String(24), nullable=False, default="member", server_default="member")
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT", name="fk_invitations_revoked_by_user")
    )
    revocation_reason: Mapped[str | None] = mapped_column(String(24))
    superseded_by_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True))
    accepted_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT", name="fk_invitations_accepted_by_user")
    )

    organisation: Mapped[Organisation] = relationship()
    invited_by: Mapped[User] = relationship(foreign_keys="OrganisationInvitation.invited_by_user_id")

    @validates("recipient_email")
    def normalize_email(self, _key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Recipient email must not be empty.")
        return value.strip().lower()


class OrganisationSettings(Timestamped, Base):
    """Tenant-specific security and operational configuration."""

    __tablename__ = "organisation_settings"
    __table_args__ = (
        CheckConstraint(
            "session_idle_timeout_minutes >= 5 AND session_idle_timeout_minutes <= 1440",
            name="ck_settings_timeout_range",
        ),
    )

    organisation_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organisations.id", ondelete="RESTRICT"), primary_key=True
    )
    allowed_email_domains: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    session_idle_timeout_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )

    organisation: Mapped[Organisation] = relationship()
