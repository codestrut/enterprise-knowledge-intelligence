"""Managed-account authentication and rotating refresh-session primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import secrets
import re
from uuid import UUID, uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from src.auth.models import (
    AuditEvent,
    Organisation,
    OrganisationMembership,
    OrganisationSettings,
    RefreshSessionRecord,
    TenantOnboarding,
    PlatformRoleAssignment,
    User,
)
from src.auth.passwords import hash_password, verify_password
from src.auth.permissions import Permission, Role


DEFAULT_SESSION_FAMILY_LIFETIME = timedelta(days=30)
DEFAULT_SESSION_IDLE_TIMEOUT = timedelta(days=7)
_GENERIC_AUTH_FAILURE = "Authentication failed. Check credentials and account access."
_DUMMY_PASSWORD_HASH = hash_password("EKIP invalid account timing sentinel")
_ROTATION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
# Namespace for this module's PostgreSQL advisory locks ("EKIP" as int4).
_FAMILY_LOCK_NAMESPACE = 0x454B4950


class AuthenticationError(Exception):
    """Non-revealing authentication or session failure."""

    def __init__(self) -> None:
        super().__init__(_GENERIC_AUTH_FAILURE)


class AuditPersistenceError(Exception):
    """A required security event could not be committed."""


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    user_id: UUID
    membership_id: UUID
    organisation_id: UUID
    role: Role
    permissions: frozenset[Permission]


@dataclass(frozen=True)
class OrganisationOption:
    id: UUID
    name: str
    slug: str


@dataclass(frozen=True)
class OrganisationSelection:
    """Safe membership choices returned only after valid credentials."""

    organisations: tuple[OrganisationOption, ...]


@dataclass(frozen=True)
class SessionGrant:
    principal: AuthenticatedPrincipal
    family_id: UUID
    refresh_token: str = field(repr=False)
    expires_at: datetime


LoginResult = SessionGrant | OrganisationSelection


def authenticate_managed_user(
    db: Session,
    email: object,
    password: object,
    *,
    organisation_id: UUID | None = None,
) -> AuthenticatedPrincipal | OrganisationSelection:
    """Verify credentials without holding a database transaction during Argon2."""
    user_id, _verified_hash = _verify_credentials(db, email, password)
    try:
        rows = db.execute(
            select(OrganisationMembership, Organisation)
            .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
            .outerjoin(TenantOnboarding, TenantOnboarding.organisation_id == Organisation.id)
            .where(
                OrganisationMembership.user_id == user_id,
                OrganisationMembership.is_active.is_(True),
                Organisation.is_active.is_(True),
                or_(TenantOnboarding.id.is_(None), TenantOnboarding.status == "active"),
            )
            .order_by(Organisation.id)
        ).all()
        return _principal_or_selection(rows, organisation_id)
    except Exception:
        db.rollback()
        raise
    finally:
        if db.in_transaction():
            db.rollback()


def _session_idle_timeout(db: Session, membership_id: UUID | None) -> timedelta:
    """Resolve the current tenant idle timeout; platform sessions use the default."""
    if membership_id is None:
        return DEFAULT_SESSION_IDLE_TIMEOUT
    organisation_id = db.scalar(
        select(OrganisationMembership.organisation_id).where(
            OrganisationMembership.id == membership_id
        )
    )
    if organisation_id is None:
        return DEFAULT_SESSION_IDLE_TIMEOUT
    minutes = db.scalar(
        select(OrganisationSettings.session_idle_timeout_minutes).where(
            OrganisationSettings.organisation_id == organisation_id
        )
    )
    if minutes is None:
        return DEFAULT_SESSION_IDLE_TIMEOUT
    return timedelta(minutes=int(minutes))


def login_managed_user(
    db: Session,
    email: object,
    password: object,
    *,
    organisation_id: UUID | None = None,
    platform_scope: bool = False,
    now: datetime | None = None,
) -> LoginResult:
    """Authenticate and create a bounded, membership-scoped session."""
    current_time = _utc_datetime(now)
    result: LoginResult | None = None

    try:
        user_id, verified_hash = _verify_credentials(db, email, password)
        with db.begin():
            user = db.scalar(select(User).where(User.id == user_id).with_for_update())
            if (
                user is None
                or not user.is_active
                or user.password_hash != verified_hash
            ):
                raise AuthenticationError

            query = (
                select(OrganisationMembership, Organisation)
                .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
                .outerjoin(TenantOnboarding, TenantOnboarding.organisation_id == Organisation.id)
                .where(
                    OrganisationMembership.user_id == user_id,
                    OrganisationMembership.is_active.is_(True),
                    Organisation.is_active.is_(True),
                    or_(TenantOnboarding.id.is_(None), TenantOnboarding.status == "active"),
                )
                .order_by(Organisation.id)
                .with_for_update(of=(OrganisationMembership, Organisation))
            )
            rows = db.execute(query).all()
            is_platform_operator = _is_platform_operator(db, user)
            if platform_scope:
                if not is_platform_operator or organisation_id is not None:
                    raise AuthenticationError
                result = _create_platform_session(db, user, current_time)
            elif not rows and is_platform_operator:
                # Platform-only operators have no tenant identity to select.
                result = _create_platform_session(db, user, current_time)
            else:
                resolved = _principal_or_selection(rows, organisation_id)
                if isinstance(resolved, OrganisationSelection):
                    result = resolved
                else:
                    family_expiry = current_time + DEFAULT_SESSION_FAMILY_LIFETIME
                    idle_timeout = _session_idle_timeout(db, resolved.membership_id)
                    expiry = min(current_time + idle_timeout, family_expiry)
                    refresh_token = secrets.token_urlsafe(32)
                    family_id = uuid4()
                    record = RefreshSessionRecord(
                        user_id=user.id,
                        membership_id=resolved.membership_id,
                        token_hash=_token_hash(refresh_token),
                        family_id=family_id,
                        created_at=current_time,
                        last_used_at=current_time,
                        expires_at=expiry,
                        family_expires_at=family_expiry,
                    )
                    db.add(record)
                    db.flush()
                    db.add(
                        AuditEvent(
                            actor_user_id=user.id,
                            organisation_id=resolved.organisation_id,
                            event_type="auth.session_created",
                            target_type="refresh_session",
                            target_id=str(record.id),
                            details={"action": "login", "outcome": "success", "membership_id": str(resolved.membership_id)},
                        )
                    )
                    result = SessionGrant(resolved, family_id, refresh_token, expiry)
    except AuthenticationError:
        db.rollback()
        _record_failed_login(db, email, organisation_id)
        raise
    except Exception:
        db.rollback()
        raise

    assert result is not None
    return result


def login_platform_operator(
    db: Session,
    email: object,
    password: object,
    *,
    now: datetime | None = None,
) -> SessionGrant:
    """Authenticate and create an independent, platform-scoped session."""
    current_time = _utc_datetime(now)
    try:
        user_id, verified_hash = _verify_credentials(db, email, password)
        with db.begin():
            user = db.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None or not user.is_active or user.password_hash != verified_hash:
                raise AuthenticationError
            if not _is_platform_operator(db, user):
                raise AuthenticationError
            return _create_platform_session(db, user, current_time)
    except AuthenticationError:
        db.rollback()
        _record_failed_login(db, email, None)
        raise
    except Exception:
        db.rollback()
        raise


def _is_platform_operator(db: Session, user: User) -> bool:
    return user.is_platform_admin is True or db.scalar(
        select(PlatformRoleAssignment.id)
        .where(PlatformRoleAssignment.user_id == user.id)
        .limit(1)
    ) is not None


def _platform_principal(user: User) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user.id,
        membership_id=UUID(int=0),
        organisation_id=UUID(int=0),
        role=Role.READER,
        permissions=frozenset(),
    )


def _create_platform_session(
    db: Session, user: User, current_time: datetime
) -> SessionGrant:
    family_expiry = current_time + DEFAULT_SESSION_FAMILY_LIFETIME
    expiry = min(current_time + DEFAULT_SESSION_IDLE_TIMEOUT, family_expiry)
    refresh_token = secrets.token_urlsafe(32)
    family_id = uuid4()
    record = RefreshSessionRecord(
        user_id=user.id,
        membership_id=None,
        token_hash=_token_hash(refresh_token),
        family_id=family_id,
        created_at=current_time,
        last_used_at=current_time,
        expires_at=expiry,
        family_expires_at=family_expiry,
    )
    db.add(record)
    db.flush()
    db.add(
        AuditEvent(
            actor_user_id=user.id,
            organisation_id=None,
            event_type="auth.platform_session_created",
            target_type="refresh_session",
            target_id=str(record.id),
            details={"action": "platform_login", "outcome": "success"},
        )
    )
    return SessionGrant(_platform_principal(user), family_id, refresh_token, expiry)


def rotate_refresh_session(
    db: Session,
    refresh_token: object,
    rotation_key: object,
    *,
    now: datetime | None = None,
) -> SessionGrant:
    """Rotate a token with retry idempotency and absolute/idle expiry.

    The caller must persist and reuse the same random rotation key for retries.
    The old refresh token alone cannot recover the replacement token. Reuse
    with a different key is treated as theft and revokes the token family.
    """
    current_time = _utc_datetime(now)
    if not isinstance(refresh_token, str) or not refresh_token:
        raise AuthenticationError
    valid_key = isinstance(rotation_key, str) and bool(_ROTATION_KEY_RE.fullmatch(rotation_key))
    key_hash = _token_hash(rotation_key) if valid_key else None

    try:
        token_hash = _token_hash(refresh_token)
        # Read the immutable session locator without a row lock. Tenant sessions
        # lock their organisation before the family advisory lock, matching the
        # lock order used by tenant suspension and logout.
        locator = db.execute(
            select(
                RefreshSessionRecord.family_id,
                RefreshSessionRecord.membership_id,
            ).where(RefreshSessionRecord.token_hash == token_hash)
        ).one_or_none()
        if locator is None:
            db.rollback()
            raise AuthenticationError

        family_id = locator.family_id
        membership_id = locator.membership_id

        # Tenant suspension takes the organisation lock before revoking refresh
        # records. Acquire that same lock before the family/token locks here.
        # This serialises refresh rotation with suspension and prevents a
        # concurrent rotation from surviving tenant reactivation.
        if membership_id is not None:
            organisation_id = db.scalar(
                select(OrganisationMembership.organisation_id).where(
                    OrganisationMembership.id == membership_id
                )
            )
            if organisation_id is None:
                db.rollback()
                raise AuthenticationError

            organisation = db.scalar(
                select(Organisation)
                .where(Organisation.id == organisation_id)
                .with_for_update()
            )
            if organisation is None or not organisation.is_active:
                db.rollback()
                raise AuthenticationError

            onboarding_status = db.scalar(
                select(TenantOnboarding.status).where(
                    TenantOnboarding.organisation_id == organisation_id
                )
            )
            if onboarding_status is not None and onboarding_status != "active":
                db.rollback()
                raise AuthenticationError

        _lock_family(db, family_id)
        record = db.scalar(
            select(RefreshSessionRecord)
            .where(RefreshSessionRecord.token_hash == token_hash)
            .with_for_update()
        )
        if record is None:
            db.rollback()
            raise AuthenticationError
        idle_timeout = _session_idle_timeout(db, record.membership_id)

        if record.revoked_at is not None:
            if record.replaced_by_id is not None and key_hash is not None and hmac.compare_digest(
                record.rotation_key_hash or "", key_hash
            ):
                replacement = db.scalar(
                    select(RefreshSessionRecord)
                    .where(RefreshSessionRecord.id == record.replaced_by_id)
                    .with_for_update()
                )
                user, membership, organisation = _lock_active_scope(
                    db, record.user_id, record.membership_id
                )
                platform_scope = record.membership_id is None and user is not None and _is_platform_operator(db, user)
                tenant_scope = record.membership_id is not None and membership is not None and organisation is not None
                replacement_scope_matches = (
                    replacement is not None
                    and ((platform_scope and replacement.membership_id is None)
                         or (tenant_scope and replacement.membership_id == membership.id))
                )
                if (
                    replacement_scope_matches
                    and replacement is not None
                    and replacement.revoked_at is None
                    and _stored_utc(replacement.expires_at) > current_time
                    and _stored_utc(replacement.family_expires_at) > current_time
                    and _stored_utc(replacement.last_used_at) + idle_timeout
                    > current_time
                    and user is not None
                ):
                    principal = (
                        _platform_principal(user)
                        if platform_scope
                        else _principal_for_user(user, membership, organisation)
                    )
                    recovered = _derive_replacement_token(refresh_token, rotation_key)
                    if hmac.compare_digest(replacement.token_hash, _token_hash(recovered)):
                        db.rollback()
                        return SessionGrant(
                            principal,
                            record.family_id,
                            recovered,
                            _stored_utc(replacement.expires_at),
                        )
                db.rollback()
                raise AuthenticationError

            if record.replaced_by_id is not None:
                _revoke_family(db, record.family_id, current_time)
                db.add(
                    AuditEvent(
                        actor_user_id=record.user_id,
                        organisation_id=_organisation_for_membership(db, record.membership_id),
                        event_type="auth.session_reuse_detected",
                        target_type="refresh_session",
                        target_id=str(record.id),
                        details={"action": "refresh", "outcome": "rejected", "reason": "reuse_detected", "family_id": str(record.family_id)},
                    )
                )
                db.commit()
            else:
                db.rollback()
            raise AuthenticationError

        if not valid_key:
            db.rollback()
            raise AuthenticationError

        if (
            _stored_utc(record.expires_at) <= current_time
            or _stored_utc(record.family_expires_at) <= current_time
            or _stored_utc(record.last_used_at) + idle_timeout <= current_time
        ):
            _revoke_family(db, record.family_id, current_time)
            db.add(
                AuditEvent(
                    actor_user_id=record.user_id,
                    organisation_id=_organisation_for_membership(db, record.membership_id),
                    event_type="auth.session_expired",
                    target_type="refresh_session",
                    target_id=str(record.id),
                    details={"action": "refresh", "outcome": "rejected", "reason": "session_expired", "family_id": str(record.family_id)},
                )
            )
            db.commit()
            raise AuthenticationError

        user, membership, organisation = _lock_active_scope(
            db, record.user_id, record.membership_id
        )
        if (
            user is None
            or (record.membership_id is not None and (membership is None or organisation is None))
            or (record.membership_id is None and not _is_platform_operator(db, user))
        ):
            _revoke_family(db, record.family_id, current_time)
            db.add(
                AuditEvent(
                    actor_user_id=record.user_id,
                    organisation_id=_organisation_for_membership(db, record.membership_id),
                    event_type="auth.session_revoked_inactive_scope",
                    target_type="refresh_session",
                    target_id=str(record.id),
                    details={"action": "refresh", "outcome": "rejected", "reason": "inactive_scope", "family_id": str(record.family_id)},
                )
            )
            db.commit()
            raise AuthenticationError

        raw_token = _derive_replacement_token(refresh_token, rotation_key)
        family_expiry = _stored_utc(record.family_expires_at)
        expiry = min(current_time + idle_timeout, family_expiry)
        replacement = RefreshSessionRecord(
            user_id=user.id,
            membership_id=membership.id if membership is not None else None,
            token_hash=_token_hash(raw_token),
            family_id=record.family_id,
            created_at=current_time,
            last_used_at=current_time,
            expires_at=expiry,
            family_expires_at=family_expiry,
        )
        db.add(replacement)
        db.flush()
        record.revoked_at = current_time
        record.last_used_at = current_time
        record.rotation_key_hash = key_hash
        record.replaced_by_id = replacement.id
        db.add(
            AuditEvent(
                actor_user_id=user.id,
                organisation_id=organisation.id if organisation is not None else None,
                event_type="auth.session_rotated",
                target_type="refresh_session",
                target_id=str(replacement.id),
                details={"action": "refresh", "outcome": "success", "family_id": str(record.family_id)},
            )
        )
        from src.auth.permissions import Role
        principal = (
            _principal_for_user(user, membership, organisation)
            if membership is not None and organisation is not None
            else _platform_principal(user)
        )
        db.commit()
        return SessionGrant(principal, record.family_id, raw_token, expiry)
    except AuthenticationError:
        raise
    except Exception:
        db.rollback()
        raise


def revoke_refresh_session(
    db: Session, refresh_token: object, *, now: datetime | None = None
) -> None:
    """Revoke a token if present; repeated or unknown logout is harmless."""
    if not isinstance(refresh_token, str) or not refresh_token:
        return
    try:
        token_hash = _token_hash(refresh_token)
        locator = db.execute(
            select(
                RefreshSessionRecord.family_id,
                RefreshSessionRecord.membership_id,
            ).where(RefreshSessionRecord.token_hash == token_hash)
        ).one_or_none()
        if locator is None:
            db.rollback()
            return

        organisation_id = _lock_organisation_for_membership(
            db, locator.membership_id
        )
        _lock_family(db, locator.family_id)
        record = db.scalar(
            select(RefreshSessionRecord)
            .where(RefreshSessionRecord.token_hash == token_hash)
            .with_for_update()
        )
        if record is not None and record.revoked_at is None:
            current_time = _utc_datetime(now)
            record.revoked_at = current_time
            db.add(
                AuditEvent(
                    actor_user_id=record.user_id,
                    organisation_id=organisation_id,
                    event_type="auth.session_revoked",
                    target_type="refresh_session",
                    target_id=str(record.id),
                    details={"action": "logout", "outcome": "success", "family_id": str(record.family_id)},
                )
            )
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise


def revoke_refresh_family(
    db: Session, family_id: UUID, *, now: datetime | None = None
) -> None:
    """Revoke every active refresh record in an authenticated session family."""
    current_time = _utc_datetime(now)
    try:
        membership_id = db.scalar(
            select(RefreshSessionRecord.membership_id)
            .where(RefreshSessionRecord.family_id == family_id)
            .order_by(RefreshSessionRecord.id)
            .limit(1)
        )
        organisation_id = _lock_organisation_for_membership(db, membership_id)
        _lock_family(db, family_id)
        records = list(
            db.scalars(
                select(RefreshSessionRecord)
                .where(RefreshSessionRecord.family_id == family_id)
                .order_by(RefreshSessionRecord.id)
                .with_for_update()
            )
        )
        changed = False
        for record in records:
            if record.revoked_at is None:
                record.revoked_at = current_time
                changed = True
        if changed and records:
            db.add(
                AuditEvent(
                    actor_user_id=records[0].user_id,
                    organisation_id=organisation_id,
                    event_type="auth.session_family_revoked",
                    target_type="refresh_session_family",
                    target_id=str(family_id),
                    details={"action": "logout", "outcome": "success", "session_count": len(records)},
                )
            )
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise


def _verify_credentials(db: Session, email: object, password: object) -> tuple[UUID, str]:
    if not isinstance(email, str) or not email.strip():
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AuthenticationError

    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None:
        db.rollback()
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AuthenticationError
    user_id, encoded_hash, active = user.id, user.password_hash, user.is_active
    db.rollback()

    if not verify_password(password, encoded_hash) or not active:
        raise AuthenticationError
    return user_id, encoded_hash


def _record_failed_login(
    db: Session, email: object, requested_organisation_id: UUID | None
) -> None:
    """Persist a non-secret failed-login event or fail the authentication request."""
    actor_user_id = None
    organisation_id = None
    try:
        if isinstance(email, str) and email.strip():
            normalized = email.strip().lower()
            user = db.scalar(select(User).where(User.email == normalized))
            if user is not None:
                actor_user_id = user.id
                memberships = set(
                    db.scalars(
                        select(OrganisationMembership.organisation_id)
                        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
                        .where(
                            OrganisationMembership.user_id == user.id,
                            OrganisationMembership.is_active.is_(True),
                            Organisation.is_active.is_(True),
                        )
                    )
                )
                if requested_organisation_id in memberships:
                    organisation_id = requested_organisation_id
                elif requested_organisation_id is None and len(memberships) == 1:
                    organisation_id = next(iter(memberships))
        db.add(
            AuditEvent(
                actor_user_id=actor_user_id,
                organisation_id=organisation_id,
                event_type="auth.login_failed",
                target_type="authentication_attempt",
                details={"action": "login", "outcome": "failure", "reason": "invalid_credentials"},
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise AuditPersistenceError("Required authentication audit could not be persisted.") from exc


def _organisation_for_membership(db: Session, membership_id: UUID | None) -> UUID | None:
    if membership_id is None:
        return None
    return db.scalar(
        select(OrganisationMembership.organisation_id).where(
            OrganisationMembership.id == membership_id
        )
    )


def _lock_organisation_for_membership(
    db: Session, membership_id: UUID | None
) -> UUID | None:
    """Lock a tenant organisation before a refresh-family lock, if applicable.

    This is a coordination lock, not an authorisation check. Logout and
    revocation must remain possible when an organisation is suspended.
    """
    organisation_id = _organisation_for_membership(db, membership_id)
    if organisation_id is None:
        return None

    locked_id = db.scalar(
        select(Organisation.id)
        .where(Organisation.id == organisation_id)
        .with_for_update()
    )
    return organisation_id if locked_id is not None else None


def _principal_or_selection(rows, organisation_id: UUID | None) -> LoginResult:
    memberships = [
        (membership, organisation)
        for membership, organisation in rows
        if membership.is_active and organisation.is_active
    ]
    if organisation_id is not None:
        memberships = [
            pair for pair in memberships if pair[0].organisation_id == organisation_id
        ]
    if not memberships:
        raise AuthenticationError
    if len(memberships) > 1:
        return OrganisationSelection(
            tuple(
                OrganisationOption(organisation.id, organisation.name, organisation.slug)
                for _membership, organisation in memberships
            )
        )
    return _principal(*memberships[0])


def _principal(
    membership: OrganisationMembership, organisation: Organisation
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=membership.user_id,
        membership_id=membership.id,
        organisation_id=organisation.id,
        role=membership.role,
        permissions=membership.permissions,
    )


def _principal_for_user(
    user: User, membership: OrganisationMembership, organisation: Organisation
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        user_id=user.id,
        membership_id=membership.id,
        organisation_id=organisation.id,
        role=membership.role,
        permissions=membership.permissions,
    )


def _lock_active_scope(
    db: Session, user_id: UUID, membership_id: UUID | None
) -> tuple[User | None, OrganisationMembership | None, Organisation | None]:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        return None, None, None
    if membership_id is None:
        return user, None, None
    membership = db.scalar(
        select(OrganisationMembership)
        .where(
            OrganisationMembership.id == membership_id,
            OrganisationMembership.user_id == user_id,
            OrganisationMembership.is_active.is_(True),
        )
        .with_for_update()
    )
    if membership is None:
        return None, None, None
    organisation = db.scalar(
        select(Organisation)
        .where(Organisation.id == membership.organisation_id)
        .with_for_update()
    )
    if organisation is None or not organisation.is_active:
        return None, None, None
    onboarding_status = db.scalar(
        select(TenantOnboarding.status).where(
            TenantOnboarding.organisation_id == organisation.id
        )
    )
    if onboarding_status is not None and onboarding_status != "active":
        return None, None, None
    return user, membership, organisation


def _revoke_family(db: Session, family_id: UUID, revoked_at: datetime) -> None:
    records = db.scalars(
        select(RefreshSessionRecord)
        .where(RefreshSessionRecord.family_id == family_id)
        .order_by(RefreshSessionRecord.id)
        .with_for_update()
    )
    for record in records:
        if record.revoked_at is None:
            record.revoked_at = revoked_at


def _lock_family(db: Session, family_id: UUID | str) -> None:
    """Serialise every change to one refresh-token family.

    Row locks cannot cover the replacement row a concurrent rotation is about
    to insert, so a family logout or reuse revocation could miss it. Refresh,
    reuse detection and logout therefore take this transaction-scoped advisory
    lock first; it is released at commit or rollback. Callers rely on READ
    COMMITTED, so statements after the lock see rows committed before it.

    Only PostgreSQL provides this guarantee. Other dialects (SQLite in unit
    tests) skip the lock, and no concurrency claim is made for them.
    """
    if db.get_bind().dialect.name != "postgresql":
        return
    family_uuid = family_id if isinstance(family_id, UUID) else UUID(str(family_id))
    key = int.from_bytes(family_uuid.bytes[:4], "big", signed=True)
    db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            "CAST(:namespace AS integer), CAST(:family_key AS integer))"
        ),
        {"namespace": _FAMILY_LOCK_NAMESPACE, "family_key": key},
    )


def _derive_replacement_token(refresh_token: str, rotation_key: str) -> str:
    message = b"ekip-refresh-rotation-v1\0" + rotation_key.encode("ascii")
    digest = hmac.new(refresh_token.encode("ascii"), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_datetime(value: datetime | None) -> datetime:
    result = datetime.now(UTC) if value is None else value
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Session timestamps must be timezone-aware.")
    return result.astimezone(UTC)


def _stored_utc(value: datetime) -> datetime:
    # SQLite drops timezone metadata from timezone-aware columns; PostgreSQL
    # preserves it. Stored timestamps are written in UTC in either backend.
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
