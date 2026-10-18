"""FastAPI dependencies for managed identity and current tenant permissions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import logging
from threading import Lock
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from src.auth.access_tokens import AccessTokenError, decode_access_token
from src.auth.database import database_url_from_environment
from src.auth.models import Organisation, OrganisationMembership, RefreshSessionRecord, User
from src.auth.permissions import Permission
from src.auth.service import AuthenticatedPrincipal


logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)
_engine_lock = Lock()
_session_factory: sessionmaker[Session] | None = None


@dataclass(frozen=True)
class AuthenticatedContext:
    principal: AuthenticatedPrincipal
    family_id: UUID


def get_auth_db():
    """Yield a database session without loading credentials or connecting at import."""
    global _session_factory
    if _session_factory is None:
        try:
            url = database_url_from_environment()
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication database is not configured.",
            ) from exc
        with _engine_lock:
            if _session_factory is None:
                from sqlalchemy import create_engine

                engine = create_engine(
                    url,
                    pool_pre_ping=True,
                    isolation_level="READ COMMITTED",
                    connect_args={
                        "options": "-c lock_timeout=5000 -c statement_timeout=15000"
                    },
                )
                _session_factory = sessionmaker(engine, expire_on_commit=False)
    db = _session_factory()
    try:
        yield db
    finally:
        if db.in_transaction():
            db.rollback()
        db.close()


def get_authenticated_context(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_auth_db),
) -> AuthenticatedContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        claims = decode_access_token(credentials.credentials)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication signing key is not configured.",
        ) from exc
    except AccessTokenError:
        raise _unauthorized()

    try:
        return _revalidate_against_database(db, claims)
    except SQLAlchemyError as exc:
        # Access stays denied; report a temporary outage instead of a generic 500.
        logger.error("Authentication store unavailable (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable.",
        ) from exc


def _revalidate_against_database(db: Session, claims) -> AuthenticatedContext:
    scope = db.execute(
        select(User, OrganisationMembership, Organisation)
        .join(OrganisationMembership, OrganisationMembership.user_id == User.id)
        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
        .where(
            User.id == claims.user_id,
            User.is_active.is_(True),
            OrganisationMembership.id == claims.membership_id,
            OrganisationMembership.organisation_id == claims.organisation_id,
            OrganisationMembership.is_active.is_(True),
            Organisation.is_active.is_(True),
        )
    ).first()
    if scope is None:
        raise _unauthorized()
    user, membership, organisation = scope
    now = datetime.now(UTC)
    active_family = db.scalar(
        select(RefreshSessionRecord.id)
        .where(
            RefreshSessionRecord.family_id == claims.family_id,
            RefreshSessionRecord.user_id == claims.user_id,
            RefreshSessionRecord.membership_id == claims.membership_id,
            RefreshSessionRecord.revoked_at.is_(None),
            RefreshSessionRecord.expires_at > now,
            RefreshSessionRecord.family_expires_at > now,
            RefreshSessionRecord.last_used_at > now - timedelta(days=7),
        )
        .limit(1)
    )
    if active_family is None:
        raise _unauthorized()

    from src.auth.permissions import permissions_for_role

    principal = AuthenticatedPrincipal(
        user_id=user.id,
        membership_id=membership.id,
        organisation_id=organisation.id,
        role=membership.role,
        permissions=permissions_for_role(membership.role),
    )
    return AuthenticatedContext(principal, claims.family_id)


def require_permission(permission: Permission):
    def dependency(
        context: AuthenticatedContext = Depends(get_authenticated_context),
    ) -> AuthenticatedContext:
        if permission not in context.principal.permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return context

    return dependency


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication is required.",
        headers={"WWW-Authenticate": "Bearer"},
    )
