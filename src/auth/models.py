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
    JSON,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates

from src.auth.permissions import Permission, Role, permissions_for_role


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
    membership_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("organisation_memberships.id", ondelete="RESTRICT"),
        nullable=False,
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
