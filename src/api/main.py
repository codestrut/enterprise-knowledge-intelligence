"""FastAPI application with managed authentication and tenant-scoped RAG."""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.api.document_fingerprints import find_duplicate_document, sha256_file
from src.api.phase1_admin_contracts import (
    AcceptInvitationRequest,
    PlatformOverviewResponse,
    TenantMemberInviteRequest,
    TenantMemberInviteResponse,
    TenantMemberUpdateRequest,
    TenantOverviewResponse,
    TenantSettingsUpdateRequest,
    TenantSettingsView,
    TenantSuspendRequest,
    TenantReactivateRequest,
)
from src.api.task06_contracts import (
    ApprovePlatformOrganisationProvisioningRequest,
    PlatformOrganisationCreateRequest,
    ProvisioningRetryRequest,
    PlatformRoleAssignmentRequest,
    ProvisioningRecoveryRequest,
)
from src.api.document_records import manifest_record, public_record, resolve_stored_path
from src.api.shared_inference import SharedGroundingEvaluator, SharedReranker
from src.api.unified_frontend import configure_unified_frontend
from src.api.tenant_storage import (
    TenantWorkspace,
    TenantWorkspaceRegistry,
    set_original_filename,
    tenant_workspace_lock,
)
from src.auth.access_tokens import (
    ACCESS_TOKEN_TTL,
    issue_access_token,
    validate_signing_key_configuration,
)
from src.auth.dependencies import (
    AuthenticatedContext,
    get_auth_db,
    get_authenticated_context,
    require_permission,
)
from src.auth.permissions import Permission, PlatformPermission, PlatformRole, Role, permissions_for_platform_role
from src.auth.models import (
    AuditEvent,
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    OrganisationSettings,
    PlatformRoleAssignment,
    RefreshSessionRecord,
    TenantOnboarding,
    User,
)
from src.auth.tenant_onboarding import (
    TenantOnboardingConflict,
    approve_and_provision_platform_organisation,
    create_platform_organisation,
    retry_platform_organisation_provisioning,
    recover_stale_platform_organisation_provisioning,
)
from src.auth.passwords import MAX_PASSWORD_CODEPOINTS, PasswordPolicyError, hash_password, verify_password
from src.auth.throttling import FailureThrottle
from src.auth.tenant_lifecycle import (
    ActivationPredicates,
    InvalidTenantTransition,
    TenantActivationDenied,
    validate_activation,
    validate_transition,
)
from src.auth.service import (
    AuthenticationError,
    AuditPersistenceError,
    OrganisationSelection,
    SessionGrant,
    login_managed_user,
    revoke_refresh_family,
    rotate_refresh_session,
)
from src.generation.grounding_evaluator import GroundingEvaluator
from src.knowledge_base import KnowledgeBase
from src.rag_pipeline import RAGPipeline


logger = logging.getLogger(__name__)
BASE_DIRECTORY = Path(__file__).resolve().parents[2]
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_QUESTION_CHARACTERS = 4000
MAX_FILENAME_CHARACTERS = 255
# Validation errors for these fields must not echo the submitted value back to the client.
_SECRET_REQUEST_FIELDS = frozenset({"password", "refresh_token", "rotation_key"})
TENANT_DATA_DIRECTORY = Path(
    os.environ.get("EKIP_TENANT_DATA_DIRECTORY", BASE_DIRECTORY / "data" / "tenants")
).expanduser()

# One shared model instance serves all isolated tenant indexes. The empty
# knowledge base is only an embedder owner; its chunks are never queried.
_shared_embedder = KnowledgeBase().embedder
_shared_reranker = SharedReranker()
_shared_grounding_evaluator = SharedGroundingEvaluator(
    lambda: GroundingEvaluator(embedder=_shared_embedder)
)
# In-process sign-in throttles (single Uvicorn worker; counters reset on restart and are not
# shared across workers). See src/auth/throttling.py for the policy and thresholds.
login_throttle = FailureThrottle()
refresh_throttle = FailureThrottle(free_failures=10)
_THROTTLED_DETAIL = "Too many sign-in attempts. Try again later."

tenant_workspaces = TenantWorkspaceRegistry(
    TENANT_DATA_DIRECTORY,
    shared_embedder=_shared_embedder,
    shared_reranker=_shared_reranker,
    pipeline_dependencies={"grounding_evaluator": _shared_grounding_evaluator},
    knowledge_base_factory=KnowledgeBase,
    pipeline_factory=RAGPipeline,
)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=320)
    password: SecretStr = Field(max_length=MAX_PASSWORD_CODEPOINTS)
    organisation_id: UUID | None = None
    auth_scope: Literal["tenant", "platform"] = "tenant"


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: SecretStr
    rotation_key: SecretStr


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARACTERS,
        description="Question to ask the knowledge base.",
    )
    top_k: int = Field(default=5, ge=1, le=20)


class OrganisationProfile(BaseModel):
    id: UUID
    name: str


class CurrentUserProfile(BaseModel):
    email: str
    organisation: OrganisationProfile | None
    role: str
    permissions: list[str]
    platform_permissions: list[str] = Field(default_factory=list)
    # Platform roles are separate from organisation membership roles. In a
    # platform-only session, `role` is only the legacy tenant-role placeholder.
    platform_roles: list[str] = Field(default_factory=list)


class AuditEventView(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    organisation_id: UUID
    event_type: str
    target_type: str | None
    target_id: str | None
    occurred_at: datetime
    details: dict[str, str | int | bool | None]


class AuditEventListResponse(BaseModel):
    count: int
    events: list[AuditEventView]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Validate required configuration, then restore tenant indexes (no legacy shared documents)."""
    # Deployment requirement: EKIP_ACCESS_TOKEN_SECRET (>= 32 bytes) must be set, otherwise the
    # service refuses to start rather than accepting logins it cannot complete.
    try:
        validate_signing_key_configuration()
    except RuntimeError as exc:
        logger.critical("Startup refused: %s", exc)
        raise RuntimeError(f"Startup refused: {exc}") from None
    tenant_workspaces.restore_all()
    yield


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


# Interactive API documentation is opt-in (isolated development/test only); never enable it
# in production.
_API_DOCS_ENABLED = _env_flag("EKIP_ENABLE_API_DOCS")

app = FastAPI(
    title="Enterprise Knowledge Intelligence Platform",
    version="1.3.0",
    lifespan=lifespan,
    docs_url="/docs" if _API_DOCS_ENABLED else None,
    redoc_url="/redoc" if _API_DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _API_DOCS_ENABLED else None,
)


configure_unified_frontend(app, BASE_DIRECTORY / "frontend" / "dist")


class SafeServerError(Exception):
    """Unexpected server failure returned with fixed text and a correlating request ID."""

    def __init__(self, status_code: int, detail: str, request_id: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.request_id = request_id


def _server_error(status_code: int, detail: str, exc: BaseException, operation: str) -> SafeServerError:
    # Log only the exception type: messages and tracebacks can carry paths or tenant content.
    request_id = uuid4().hex
    logger.error("%s failed (%s); request_id=%s", operation, type(exc).__name__, request_id)
    return SafeServerError(status_code, detail, request_id)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI's default 422 body, minus echoed values for credential fields."""
    errors = []
    for error in exc.errors():
        error = dict(error)
        if _SECRET_REQUEST_FIELDS.intersection(str(part) for part in error.get("loc", ())):
            error.pop("input", None)
            error.pop("ctx", None)
        errors.append(error)
    return JSONResponse({"detail": jsonable_encoder(errors)}, status_code=422)


@app.exception_handler(SafeServerError)
async def _safe_server_error_handler(_request: Request, exc: SafeServerError) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail, "request_id": exc.request_id},
        status_code=exc.status_code,
        headers={"X-Request-ID": exc.request_id},
    )


def _token_response(grant: SessionGrant) -> dict[str, object]:
    try:
        access = issue_access_token(grant.principal, grant.family_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication signing key is not configured.",
        ) from exc
    return {
        "access_token": access.token,
        "token_type": "bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": grant.refresh_token,
        "organisation_id": (
            None if grant.principal.organisation_id == UUID(int=0)
            else str(grant.principal.organisation_id)
        ),
        "role": grant.principal.role.value,
        "permissions": sorted(permission.value for permission in grant.principal.permissions),
    }


def _audit_unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Security audit persistence is unavailable. Refresh the resource status before retrying.",
    )


def _commit_audit(db: Session) -> None:
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error("Security audit persistence failed (%s).", type(exc).__name__)
        raise _audit_unavailable() from exc


def _start_audit_event(
    db: Session,
    context: AuthenticatedContext,
    *,
    event_type: str,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, str | int | bool | None] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=context.principal.user_id,
        organisation_id=context.principal.organisation_id,
        event_type=event_type,
        target_type=target_type,
        target_id=target_id,
        details={"action": event_type, "outcome": "started", **(details or {})},
    )
    db.add(event)
    _commit_audit(db)
    return event


def _finish_audit_event(
    db: Session,
    event: AuditEvent,
    *,
    outcome: str,
    reason: str | None = None,
) -> None:
    details = dict(event.details or {})
    details["outcome"] = outcome
    if reason is not None:
        details["reason"] = reason
    event.details = details
    db.add(event)
    _commit_audit(db)


def _client_address(request: Request) -> str:
    # Direct peer address only; forwarded headers are not trusted here.
    return request.client.host if request.client is not None else "unknown"


def _throttled(retry_after: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=_THROTTLED_DETAIL,
        headers={"Retry-After": str(retry_after)},
    )


@app.post("/auth/login")
def auth_login(request: Request, body: LoginRequest, db: Session = Depends(get_auth_db)):
    address = _client_address(request)
    retry_after = login_throttle.retry_after(address, body.email)
    if retry_after is not None:
        raise _throttled(retry_after)
    try:
        result = login_managed_user(
            db,
            body.email,
            body.password.get_secret_value(),
            organisation_id=body.organisation_id,
            platform_scope=body.auth_scope == "platform",
        )
    except AuthenticationError as exc:
        login_throttle.record_failure(address, body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except AuditPersistenceError as exc:
        raise _audit_unavailable() from exc
    except SQLAlchemyError as exc:
        logger.error("Authentication audit/session persistence failed (%s).", type(exc).__name__)
        raise _audit_unavailable() from exc
    login_throttle.record_success(address, body.email)
    if isinstance(result, OrganisationSelection):
        return {
            "requires_organisation_selection": True,
            "organisations": [
                {"id": str(item.id), "name": item.name, "slug": item.slug}
                for item in result.organisations
            ],
        }
    return _token_response(result)


@app.post("/auth/refresh")
def auth_refresh(request: Request, body: RefreshRequest, db: Session = Depends(get_auth_db)):
    address = _client_address(request)
    retry_after = refresh_throttle.retry_after(address)
    if retry_after is not None:
        raise _throttled(retry_after)
    try:
        grant = rotate_refresh_session(
            db,
            body.refresh_token.get_secret_value(),
            body.rotation_key.get_secret_value(),
        )
    except AuthenticationError as exc:
        # Only rejected tokens count; a valid same-key retry succeeds and is never counted.
        refresh_throttle.record_failure(address)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except SQLAlchemyError as exc:
        logger.error("Refresh audit/session persistence failed (%s).", type(exc).__name__)
        raise _audit_unavailable() from exc
    refresh_throttle.record_success(address)
    return _token_response(grant)


@app.post("/auth/logout", status_code=204)
def auth_logout(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    try:
        revoke_refresh_family(db, context.family_id)
    except SQLAlchemyError as exc:
        logger.error("Logout audit/session persistence failed (%s).", type(exc).__name__)
        raise _audit_unavailable() from exc
    return None


@app.get("/auth/me", response_model=CurrentUserProfile)
def auth_me(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Return only the identity and tenant scope resolved by auth middleware."""
    principal = context.principal
    if principal.organisation_id == UUID(int=0) or principal.membership_id == UUID(int=0):
        actor = db.get(User, principal.user_id)
        if actor is None or not actor.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication is required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return CurrentUserProfile(
            email=actor.email,
            organisation=None,
            role=principal.role.value,
            permissions=[],
            platform_permissions=sorted(
                permission.value for permission in _platform_permissions_for_actor(db, actor)
            ),
            platform_roles=_platform_roles_for_actor(db, actor),
        )
    scope = db.execute(
        select(User.email, Organisation.id, Organisation.name)
        .join(OrganisationMembership, OrganisationMembership.user_id == User.id)
        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
        .where(
            User.id == principal.user_id,
            User.is_active.is_(True),
            OrganisationMembership.id == principal.membership_id,
            OrganisationMembership.organisation_id == principal.organisation_id,
            OrganisationMembership.is_active.is_(True),
            Organisation.is_active.is_(True),
        )
    ).one_or_none()
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    email, organisation_id, organisation_name = scope
    actor = db.get(User, principal.user_id)
    return CurrentUserProfile(
        email=email,
        organisation=OrganisationProfile(id=organisation_id, name=organisation_name),
        role=principal.role.value,
        permissions=sorted(permission.value for permission in principal.permissions),
        platform_permissions=sorted(permission.value for permission in _platform_permissions_for_actor(db, actor)),
        platform_roles=_platform_roles_for_actor(db, actor),
    )


@app.get("/audit/events", response_model=AuditEventListResponse)
def list_audit_events(
    limit: int = Query(default=50, ge=1, le=100),
    before: datetime | None = None,
    context: AuthenticatedContext = Depends(require_permission(Permission.AUDIT_READ)),
    db: Session = Depends(get_auth_db),
):
    """Read only events scoped to the caller's authorized organisation membership."""
    statement = select(AuditEvent).where(
        AuditEvent.organisation_id == context.principal.organisation_id
    )
    if before is not None:
        statement = statement.where(AuditEvent.occurred_at < before)
    events = db.scalars(
        statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit)
    ).all()
    return {
        "count": len(events),
        "events": [
            {
                "id": event.id,
                "actor_user_id": event.actor_user_id,
                "organisation_id": event.organisation_id,
                "event_type": event.event_type,
                "target_type": event.target_type,
                "target_id": event.target_id,
                "occurred_at": event.occurred_at,
                "details": event.details,
            }
            for event in events
        ],
    }



# ---------------------------------------------------------------------------
# Tenant administration: all queries are constrained to the authenticated org.
# ---------------------------------------------------------------------------


def _tenant_settings(db: Session, organisation_id: UUID) -> OrganisationSettings | None:
    return db.scalar(
        select(OrganisationSettings).where(
            OrganisationSettings.organisation_id == organisation_id
        )
    )


def _validate_allowed_domains(domains: list[str]) -> list[str]:
    import re

    normalized = sorted({domain.strip().lower().lstrip("@") for domain in domains if domain.strip()})
    pattern = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
    if any(not pattern.fullmatch(domain) for domain in normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Allowed email domains must be valid DNS domain names.",
        )
    return normalized


def _lock_invitation_organisation(db: Session, organisation_id: UUID) -> None:
    """Serialize invitation creation for one organisation.

    The lock must be acquired before checking for a pending invitation and held
    through commit. PostgreSQL READ COMMITTED gives a waiting request a fresh
    snapshot for the duplicate query after the previous creator commits.
    """
    locked_organisation = db.execute(
        select(Organisation.id, Organisation.is_active)
        .where(Organisation.id == organisation_id)
        .with_for_update()
    ).one_or_none()
    if locked_organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    if not locked_organisation.is_active:
        raise HTTPException(status_code=403, detail="Tenant organisation is not active.")


def _assert_invitation_domain_allowed(
    db: Session, organisation_id: UUID, email: str
) -> None:
    settings = _tenant_settings(db, organisation_id)
    allowed = set(settings.allowed_email_domains or []) if settings else set()
    if allowed and email.rsplit("@", 1)[-1].lower() not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The recipient email domain is not permitted by this organisation.",
        )


def _invitation_tokens_may_be_returned() -> bool:
    """Allow raw invitation tokens only in explicitly named non-production environments.

    Unknown, missing, staging, and production environment labels fail closed.
    An explicit feature flag is still required in every allowed environment.
    """
    environment = (
        os.environ.get("EKIP_ENV")
        or os.environ.get("ENVIRONMENT")
        or ""
    ).strip().lower()
    allowed_environments = {"dev", "development", "test", "testing"}
    return environment in allowed_environments and _env_flag(
        "EKIP_EXPOSE_INVITATION_TOKENS"
    )


def _audit_tenant_admin_action(
    db: Session,
    context: AuthenticatedContext,
    *,
    event_type: str,
    target_type: str,
    target_id: str,
    details: dict[str, str | int | bool | None] | None = None,
) -> None:
    db.add(
        AuditEvent(
            actor_user_id=context.principal.user_id,
            organisation_id=context.principal.organisation_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            details={"action": event_type, "outcome": "success", **(details or {})},
        )
    )


def _active_admin_count(db: Session, organisation_id: UUID) -> int:
    """Count only enabled users with active administrator memberships."""
    return int(
        db.scalar(
            select(func.count(OrganisationMembership.id))
            .join(User, User.id == OrganisationMembership.user_id)
            .where(
                OrganisationMembership.organisation_id == organisation_id,
                OrganisationMembership.role == Role.ORGANISATION_ADMINISTRATOR,
                OrganisationMembership.is_active.is_(True),
                User.is_active.is_(True),
            )
        )
        or 0
    )


def _protect_last_active_admin(
    db: Session,
    membership: OrganisationMembership,
    *,
    next_role: Role | None = None,
    next_active: bool | None = None,
) -> None:
    removes_admin = (
        membership.role == Role.ORGANISATION_ADMINISTRATOR
        and membership.is_active
        and (
            (next_role is not None and next_role != Role.ORGANISATION_ADMINISTRATOR)
            or next_active is False
        )
    )
    if removes_admin and _active_admin_count(db, membership.organisation_id) <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot demote or remove the last active organisation administrator.",
        )


def _revoke_membership_sessions(db: Session, membership_id: UUID) -> None:
    now = datetime.now(UTC)
    sessions = db.scalars(
        select(RefreshSessionRecord).where(
            RefreshSessionRecord.membership_id == membership_id,
            RefreshSessionRecord.revoked_at.is_(None),
        )
    ).all()
    for session in sessions:
        session.revoked_at = now


def _revoke_organisation_sessions(
    db: Session,
    organisation_id: UUID,
    *,
    revoked_at: datetime,
) -> int:
    """Revoke every active refresh-session record scoped to one organisation.

    Suspension holds the organisation row lock before this update. Refresh
    rotation follows the same organisation-before-session lock order, so no
    tenant refresh can race past suspension and survive a later reactivation.
    """
    membership_ids = select(OrganisationMembership.id).where(
        OrganisationMembership.organisation_id == organisation_id
    )
    result = db.execute(
        update(RefreshSessionRecord)
        .where(
            RefreshSessionRecord.membership_id.in_(membership_ids),
            RefreshSessionRecord.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0)


@app.get("/tenant/overview", response_model=TenantOverviewResponse)
def tenant_admin_overview(
    context: AuthenticatedContext = Depends(require_permission(Permission.TENANT_READ)),
    db: Session = Depends(get_auth_db),
):
    organisation = db.get(Organisation, context.principal.organisation_id)
    if organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    workspace = _workspace(context)
    with tenant_workspace_lock(workspace, write=False):
        manifest = workspace.read_manifest()
        records = list(manifest.values())
        documents = len(records)
        chunks = sum(int(record.get("chunk_count", 0) or 0) for record in records)
        failed = sum(1 for record in records if record.get("status") == "failed")
    members = _active_admin_count(db, organisation.id)
    non_admin_members = int(
        db.scalar(
            select(func.count(OrganisationMembership.id)).where(
                OrganisationMembership.organisation_id == organisation.id,
                OrganisationMembership.is_active.is_(True),
                OrganisationMembership.role != Role.ORGANISATION_ADMINISTRATOR,
            )
        )
        or 0
    )
    return TenantOverviewResponse(
        organisation_id=organisation.id,
        organisation_name=organisation.name,
        document_count=documents,
        chunk_count=chunks,
        failed_document_count=failed,
        member_count=members + non_admin_members,
    )


@app.get("/tenant/members")
def tenant_list_members(
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    rows = db.execute(
        select(OrganisationMembership, User)
        .join(User, User.id == OrganisationMembership.user_id)
        .where(OrganisationMembership.organisation_id == context.principal.organisation_id)
        .order_by(User.email, OrganisationMembership.id)
    ).all()
    return {
        "count": len(rows),
        "members": [
            {
                "id": str(membership.id),
                "user_id": str(user.id),
                "email": user.email,
                "role": membership.role.value,
                "is_active": membership.is_active,
                "created_at": membership.created_at.isoformat(),
            }
            for membership, user in rows
        ],
    }


@app.patch("/tenant/members/{membership_id}")
def tenant_update_member(
    membership_id: UUID,
    body: TenantMemberUpdateRequest,
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    organisation_id = context.principal.organisation_id
    # Lock the organisation row first. All membership-admin mutations follow
    # this lock order, serialising last-admin checks on PostgreSQL.
    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    membership = db.scalar(
        select(OrganisationMembership)
        .where(
            OrganisationMembership.id == membership_id,
            OrganisationMembership.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organisation member was not found.")
    if body.role is None and body.is_active is None:
        raise HTTPException(status_code=422, detail="At least one member field must be supplied.")
    _protect_last_active_admin(
        db, membership, next_role=body.role, next_active=body.is_active
    )
    old_role = membership.role.value
    if body.role is not None:
        membership.role = body.role
    if body.is_active is not None:
        membership.is_active = body.is_active
        if not body.is_active:
            _revoke_membership_sessions(db, membership.id)
    _audit_tenant_admin_action(
        db,
        context,
        event_type="tenant.member_updated",
        target_type="membership",
        target_id=str(membership.id),
        details={
            "previous_role": old_role,
            "role": membership.role.value,
            "is_active": membership.is_active,
        },
    )
    db.commit()
    return {
        "id": str(membership.id),
        "user_id": str(membership.user_id),
        "role": membership.role.value,
        "is_active": membership.is_active,
    }


@app.delete("/tenant/members/{membership_id}")
def tenant_remove_member(
    membership_id: UUID,
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    organisation_id = context.principal.organisation_id
    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    membership = db.scalar(
        select(OrganisationMembership)
        .where(
            OrganisationMembership.id == membership_id,
            OrganisationMembership.organisation_id == organisation_id,
        )
        .with_for_update()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Organisation member was not found.")
    _protect_last_active_admin(db, membership, next_active=False)
    membership.is_active = False
    _revoke_membership_sessions(db, membership.id)
    _audit_tenant_admin_action(
        db,
        context,
        event_type="tenant.member_removed",
        target_type="membership",
        target_id=str(membership.id),
        details={"is_active": False},
    )
    db.commit()
    return {"id": str(membership.id), "removed": True}


@app.post("/tenant/members/invitations", response_model=TenantMemberInviteResponse, status_code=201)
def tenant_create_invitation(
    body: TenantMemberInviteRequest,
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    """Issue or resend a member invitation, preserving the replaced row."""
    if not _invitation_tokens_may_be_returned():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Invitation delivery is not configured. Configure an email delivery provider, "
                "or explicitly enable EKIP_EXPOSE_INVITATION_TOKENS in a non-production environment."
            ),
        )
    if body.message is not None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Custom invitation messages require an outbound email delivery provider.",
        )
    email = body.recipient_email
    organisation_id = context.principal.organisation_id
    _lock_invitation_organisation(db, organisation_id)
    _assert_invitation_domain_allowed(db, organisation_id, email)
    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user is not None:
        existing_membership = db.scalar(
            select(OrganisationMembership)
            .where(
                OrganisationMembership.organisation_id == organisation_id,
                OrganisationMembership.user_id == existing_user.id,
            )
            .with_for_update()
        )
        if existing_membership is not None:
            if existing_membership.is_active:
                raise HTTPException(
                    status_code=409,
                    detail="This user is already an active organisation member.",
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "This user already has an inactive organisation membership. "
                    "Reactivate the existing membership instead of issuing a new invitation."
                ),
            )

    now = datetime.now(UTC)
    previous = db.scalars(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.organisation_id == organisation_id,
            OrganisationInvitation.recipient_email == email,
            OrganisationInvitation.accepted_at.is_(None),
            OrganisationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    # Expired rows still occupy the database's open-invitation index until
    # transitioned. A live duplicate is a conflict; callers use the explicit
    # resend endpoint when they intend to rotate an existing token.
    for old in previous:
        expires_at = old.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > now:
            raise HTTPException(status_code=409, detail="A pending invitation already exists for this email address.")
        old.revoked_at = now
        old.revocation_reason = "expired"
        old.revoked_by_user_id = None
        old.superseded_by_id = None
    if previous:
        db.flush()

    raw_token = secrets.token_urlsafe(32)
    invitation = OrganisationInvitation(
        organisation_id=organisation_id,
        recipient_email=email,
        role=body.role.value,
        purpose="member",
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        invited_by_user_id=context.principal.user_id,
        expires_at=now + timedelta(days=7),
    )
    db.add(invitation)
    db.flush()
    _audit_tenant_admin_action(
        db,
        context,
        event_type="tenant.invitation_created",
        target_type="invitation",
        target_id=str(invitation.id),
        details={"recipient_email": email, "role": body.role.value, "expired_open_count": len(previous)},
    )
    db.commit()
    return TenantMemberInviteResponse(
        id=invitation.id,
        recipient_email=email,
        role=body.role.value,
        invitation_token=raw_token,
        expires_at=invitation.expires_at.isoformat(),
    )


@app.post("/tenant/members/invitations/{invitation_id}/resend", response_model=TenantMemberInviteResponse, status_code=201)
def tenant_resend_invitation(
    invitation_id: UUID,
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    """Rotate a pending invitation and retain the previous row as superseded."""
    if not _invitation_tokens_may_be_returned():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Invitation delivery is not configured. Configure an outbound email provider before production use.",
        )
    organisation_id = context.principal.organisation_id
    _lock_invitation_organisation(db, organisation_id)
    old = db.scalar(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.id == invitation_id,
            OrganisationInvitation.organisation_id == organisation_id,
            OrganisationInvitation.purpose == "member",
            OrganisationInvitation.accepted_at.is_(None),
            OrganisationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if old is None:
        raise HTTPException(status_code=404, detail="Pending invitation was not found.")
    email = old.recipient_email
    _assert_invitation_domain_allowed(db, organisation_id, email)
    now = datetime.now(UTC)
    old_expiry = old.expires_at
    if old_expiry.tzinfo is None:
        old_expiry = old_expiry.replace(tzinfo=UTC)
    replacement_id = uuid4()
    old.revoked_at = now
    if old_expiry <= now:
        old.revocation_reason = "expired"
        old.revoked_by_user_id = None
        old.superseded_by_id = None
    else:
        old.revocation_reason = "superseded"
        old.revoked_by_user_id = context.principal.user_id
        old.superseded_by_id = replacement_id
    db.flush()

    raw_token = secrets.token_urlsafe(32)
    replacement = OrganisationInvitation(
        id=replacement_id,
        organisation_id=organisation_id,
        recipient_email=email,
        role=old.role,
        purpose="member",
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        invited_by_user_id=context.principal.user_id,
        expires_at=now + timedelta(days=7),
    )
    db.add(replacement)
    db.flush()
    _audit_tenant_admin_action(
        db,
        context,
        event_type="tenant.invitation_resent",
        target_type="invitation",
        target_id=str(replacement.id),
        details={"recipient_email": email, "role": old.role},
    )
    db.commit()
    return TenantMemberInviteResponse(
        id=replacement.id,
        recipient_email=email,
        role=old.role,
        invitation_token=raw_token,
        expires_at=replacement.expires_at.isoformat(),
    )


@app.get("/tenant/members/invitations")
def tenant_list_invitations(
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    now = datetime.now(UTC)
    rows = db.execute(
        select(OrganisationInvitation, User.email)
        .join(User, User.id == OrganisationInvitation.invited_by_user_id)
        .where(
            OrganisationInvitation.organisation_id == context.principal.organisation_id,
            OrganisationInvitation.accepted_at.is_(None),
            OrganisationInvitation.revoked_at.is_(None),
            OrganisationInvitation.expires_at > now,
        )
        .order_by(OrganisationInvitation.created_at.desc())
    ).all()
    return {
        "count": len(rows),
        "invitations": [
            {
                "id": str(invitation.id),
                "recipient_email": invitation.recipient_email,
                "role": invitation.role,
                "invited_by_email": invited_by_email,
                "expires_at": invitation.expires_at.isoformat(),
                "created_at": invitation.created_at.isoformat(),
            }
            for invitation, invited_by_email in rows
        ],
    }


@app.delete("/tenant/members/invitations/{invitation_id}")
def tenant_revoke_invitation(
    invitation_id: UUID,
    context: AuthenticatedContext = Depends(require_permission(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_auth_db),
):
    organisation_id = context.principal.organisation_id
    _lock_invitation_organisation(db, organisation_id)
    invitation = db.scalar(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.id == invitation_id,
            OrganisationInvitation.organisation_id == organisation_id,
            OrganisationInvitation.accepted_at.is_(None),
            OrganisationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Pending invitation was not found.")
    now = datetime.now(UTC)
    invitation.revoked_at = now
    invitation.revoked_by_user_id = context.principal.user_id
    invitation.revocation_reason = "revoked_by_admin"
    _audit_tenant_admin_action(
        db,
        context,
        event_type="tenant.invitation_revoked",
        target_type="invitation",
        target_id=str(invitation.id),
        details={"reason": "revoked_by_admin"},
    )
    db.commit()
    return {"id": str(invitation.id), "revoked": True}


@app.post("/auth/invitations/accept", status_code=200)
def accept_tenant_invitation(
    body: AcceptInvitationRequest,
    db: Session = Depends(get_auth_db),
):
    """Accept a single-use invitation; initial-admin acceptance activates onboarding."""
    raw_token = body.token.get_secret_value()
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    locator = db.execute(
        select(OrganisationInvitation.id, OrganisationInvitation.organisation_id)
        .where(OrganisationInvitation.token_hash == token_hash)
    ).one_or_none()
    if locator is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invitation is invalid or has expired.")

    # Match the issuer/revoker lock order: organisation first, invitation second.
    organisation = db.scalar(
        select(Organisation)
        .where(Organisation.id == locator.organisation_id)
        .with_for_update()
    )
    invitation = db.scalar(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.id == locator.id,
            OrganisationInvitation.token_hash == token_hash,
        )
        .with_for_update()
    )
    if invitation is None or organisation is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invitation is invalid or has expired.")
    if invitation.accepted_at is not None:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invitation has already been accepted.")
    if invitation.revoked_at is not None:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invitation is invalid or has expired.")
    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now:
        db.rollback()
        raise HTTPException(status_code=400, detail="Invitation is invalid or has expired.")

    onboarding = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation.id)
        .with_for_update()
    )
    is_initial_admin = invitation.purpose == "initial_admin"
    activation_source_status = onboarding.status if onboarding is not None else None
    if is_initial_admin:
        if (
            organisation.is_active
            or onboarding is None
            or onboarding.status != "pending_admin"
            or onboarding.provisioning_completed_at is None
            or onboarding.approved_by_user_id is None
            or onboarding.initial_admin_invitation_id != invitation.id
            or onboarding.initial_admin_invitation_accepted_at is not None
            or onboarding.initial_admin_email != invitation.recipient_email
            or invitation.role != Role.ORGANISATION_ADMINISTRATOR.value
        ):
            db.rollback()
            raise HTTPException(status_code=409, detail="Initial administrator activation requirements are not satisfied.")
    else:
        if not organisation.is_active:
            db.rollback()
            raise HTTPException(status_code=403, detail="Tenant organisation is not active.")
        if onboarding is not None and onboarding.status != "active":
            db.rollback()
            raise HTTPException(status_code=403, detail="Tenant organisation is not active.")

    _assert_invitation_domain_allowed(db, organisation.id, invitation.recipient_email)
    password = body.password.get_secret_value()
    try:
        user = db.scalar(select(User).where(User.email == invitation.recipient_email).with_for_update())
        if user is None:
            user = User(email=invitation.recipient_email, password_hash=hash_password(password))
            db.add(user)
            db.flush()
        elif not verify_password(password, user.password_hash):
            db.rollback()
            raise HTTPException(status_code=401, detail="Invitation acceptance could not be authenticated.")
        if not user.is_active:
            db.rollback()
            raise HTTPException(status_code=403, detail="This user account is not active.")
        existing = db.scalar(
            select(OrganisationMembership.id).where(
                OrganisationMembership.organisation_id == organisation.id,
                OrganisationMembership.user_id == user.id,
            )
        )
        if existing is not None:
            db.rollback()
            raise HTTPException(status_code=409, detail="An organisation membership already exists for this user.")
        membership = OrganisationMembership(
            organisation_id=organisation.id,
            user_id=user.id,
            role=Role(invitation.role),
            is_active=True,
        )
        db.add(membership)
        invitation.accepted_at = now
        invitation.accepted_by_user_id = user.id
        db.add(
            AuditEvent(
                actor_user_id=user.id,
                organisation_id=organisation.id,
                event_type="tenant.invitation_accepted",
                target_type="invitation",
                target_id=str(invitation.id),
                details={"action": "invitation_accepted", "outcome": "success", "role": invitation.role},
            )
        )
        if is_initial_admin:
            onboarding.initial_admin_invitation_accepted_at = now
            onboarding.status = "active"
            organisation.is_active = True
            db.add(
                AuditEvent(
                    actor_user_id=user.id,
                    organisation_id=organisation.id,
                    event_type="tenant_activated",
                    target_type="organisation",
                    target_id=str(organisation.id),
                    details={"action": "tenant_activated", "outcome": "success", "source": "initial_admin_invitation"},
                )
            )
            db.flush()
            try:
                validate_transition(activation_source_status, "active")
                validate_activation(
                    activation_source_status,
                    ActivationPredicates(
                        requester_email_verified=True,
                        organisational_review_approved=onboarding.approved_by_user_id is not None,
                        provisioning_completed_and_reconciled=onboarding.provisioning_completed_at is not None,
                        invitation_valid=True,
                        invitation_single_use=(
                            invitation.accepted_at == now
                            and invitation.accepted_by_user_id == user.id
                            and invitation.revoked_at is None
                        ),
                        invitation_bound_to_tenant=(invitation.organisation_id == onboarding.organisation_id),
                        invitation_bound_to_email=(invitation.recipient_email == onboarding.initial_admin_email),
                        invitation_role_is_initial_admin=(invitation.purpose == "initial_admin" and invitation.role == Role.ORGANISATION_ADMINISTRATOR.value),
                        initial_admin_identity_verified=(user.is_active and user.email == invitation.recipient_email),
                        membership_can_be_established=(membership.organisation_id == organisation.id and membership.user_id == user.id and membership.is_active and membership.role == Role.ORGANISATION_ADMINISTRATOR),
                        required_audit_events_persisted=True,
                    ),
                )
            except (InvalidTenantTransition, TenantActivationDenied, ValueError) as exc:
                db.rollback()
                raise HTTPException(status_code=409, detail="Tenant activation requirements are not satisfied.") from exc
        db.commit()
    except PasswordPolicyError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
    return {
        "accepted": True,
        "email": user.email,
        "organisation_id": str(organisation.id),
        "role": membership.role.value,
        "tenant_activated": is_initial_admin,
    }


@app.get("/tenant/settings", response_model=TenantSettingsView)
def tenant_get_settings(
    context: AuthenticatedContext = Depends(require_permission(Permission.AUTH_CONFIGURE)),
    db: Session = Depends(get_auth_db),
):
    settings = _tenant_settings(db, context.principal.organisation_id)
    return TenantSettingsView(
        organisation_id=context.principal.organisation_id,
        allowed_email_domains=settings.allowed_email_domains if settings else [],
        session_idle_timeout_minutes=settings.session_idle_timeout_minutes if settings else 60,
    )


@app.patch("/tenant/settings", response_model=TenantSettingsView)
def tenant_update_settings(
    body: TenantSettingsUpdateRequest,
    context: AuthenticatedContext = Depends(require_permission(Permission.AUTH_CONFIGURE)),
    db: Session = Depends(get_auth_db),
):
    organisation_id = context.principal.organisation_id
    supplied_fields = set(body.model_fields_set)
    if not supplied_fields:
        raise HTTPException(status_code=422, detail="At least one tenant setting must be supplied.")
    settings = db.scalar(
        select(OrganisationSettings)
        .where(OrganisationSettings.organisation_id == organisation_id)
        .with_for_update()
    )
    # PATCH must preserve every omitted setting rather than resetting it to a
    # request-model default.
    if "allowed_email_domains" in supplied_fields:
        domains = _validate_allowed_domains(body.allowed_email_domains)
    else:
        domains = list(settings.allowed_email_domains or []) if settings else []
    if "session_idle_timeout_minutes" in supplied_fields:
        idle_timeout_minutes = body.session_idle_timeout_minutes
    else:
        idle_timeout_minutes = settings.session_idle_timeout_minutes if settings else 60
    if settings is None:
        settings = OrganisationSettings(
            organisation_id=organisation_id,
            allowed_email_domains=domains,
            session_idle_timeout_minutes=idle_timeout_minutes,
        )
        db.add(settings)
    else:
        settings.allowed_email_domains = domains
        settings.session_idle_timeout_minutes = idle_timeout_minutes
    _audit_tenant_admin_action(
        db,
        context,
        event_type="tenant.settings_updated",
        target_type="organisation_settings",
        target_id=str(organisation_id),
        details={"allowed_domain_count": len(domains), "session_idle_timeout_minutes": idle_timeout_minutes},
    )
    db.commit()
    return TenantSettingsView(
        organisation_id=organisation_id,
        allowed_email_domains=domains,
        session_idle_timeout_minutes=idle_timeout_minutes,
    )

def _workspace(context: AuthenticatedContext) -> TenantWorkspace:
    return tenant_workspaces.workspace_for(context.principal.organisation_id)


def _platform_roles_for_actor(db: Session, actor: User) -> list[str]:
    """Return explicit platform role assignments separately from tenant roles."""
    return sorted(
        {
            assignment.role
            for assignment in db.scalars(
                select(PlatformRoleAssignment).where(PlatformRoleAssignment.user_id == actor.id)
            ).all()
        }
    )


def _platform_permissions_for_actor(db: Session, actor: User) -> frozenset[PlatformPermission]:
    """Resolve explicit platform role assignments; legacy admins remain super-admins."""
    if actor.is_platform_admin is True:
        return frozenset(PlatformPermission)
    assignments = db.scalars(
        select(PlatformRoleAssignment).where(PlatformRoleAssignment.user_id == actor.id)
    ).all()
    return frozenset(
        permission
        for assignment in assignments
        for permission in permissions_for_platform_role(assignment.role)
    )


def _require_platform_permission(
    db: Session,
    actor: User | None,
    context: AuthenticatedContext,
    permission: PlatformPermission,
) -> None:
    if (
        context.principal.membership_id != UUID(int=0)
        or context.principal.organisation_id != UUID(int=0)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A platform-scoped session is required.",
        )
    if actor is None or permission not in _platform_permissions_for_actor(db, actor):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Required platform permission is missing.")


def _platform_audit_event(
    db: Session,
    actor: User,
    *,
    event_type: str,
    target_type: str,
    target_id: str,
    reason_code: str | None = None,
) -> None:
    # Platform governance events are global records. Free-text notes are not
    # persisted here because global audit readers must not receive arbitrary
    # tenant-supplied content.
    details: dict[str, str | int | bool | None] = {
        "action": event_type,
        "outcome": "success",
    }
    if reason_code:
        details["reason_code"] = reason_code
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            organisation_id=None,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            details=details,
        )
    )


def _safe_platform_audit_details(details: dict | None) -> dict[str, str | int | bool | None]:
    """Expose only reviewed operational fields; never forward arbitrary event payloads."""
    if not isinstance(details, dict):
        return {}
    allowed = {
        "action",
        "outcome",
        "reason_code",
        "role",
        "session_count",
        "attempt",
        "allowed_domain_count",
        "session_idle_timeout_minutes",
        "provisioning_attempts",
    }
    return {
        key: value
        for key, value in details.items()
        if key in allowed and (value is None or isinstance(value, (str, int, bool)))
    }


@app.get("/platform/overview", response_model=PlatformOverviewResponse)
def platform_overview(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_READ)
    rows = db.execute(
        select(Organisation, TenantOnboarding)
        .outerjoin(TenantOnboarding, TenantOnboarding.organisation_id == Organisation.id)
        .order_by(Organisation.id)
    ).all()
    statuses = [
        onboarding.status if onboarding is not None else ("active" if organisation.is_active else "suspended")
        for organisation, onboarding in rows
    ]
    total_documents = 0
    total_chunks = 0
    for organisation, _onboarding in rows:
        workspace = tenant_workspaces.workspace_for(organisation.id)
        with tenant_workspace_lock(workspace, write=False):
            manifest = workspace.read_manifest()
            total_documents += len(manifest)
            total_chunks += sum(
                int(record.get("chunk_count", 0) or 0)
                for record in manifest.values()
            )
    return PlatformOverviewResponse(
        total_tenants=len(rows),
        active_tenants=sum(1 for (organisation, _), value in zip(rows, statuses) if value == "active" and organisation.is_active),
        pending_tenants=sum(1 for value in statuses if value in {"registration_pending", "pending_admin"}),
        provisioning_tenants=sum(1 for value in statuses if value == "provisioning"),
        failed_tenants=sum(1 for value in statuses if value == "provisioning_failed"),
        suspended_tenants=sum(
            1
            for (organisation, onboarding), value in zip(rows, statuses)
            if value == "suspended"
            or (onboarding is None and not organisation.is_active)
        ),
        total_documents=total_documents,
        total_chunks=total_chunks,
    )


@app.post("/platform/organisations/{organisation_id}/suspend")
def suspend_platform_organisation(
    organisation_id: UUID,
    body: TenantSuspendRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_SUSPEND)
    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    onboarding = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation_id)
        .with_for_update()
    )
    if onboarding is not None and onboarding.status != "active":
        raise HTTPException(
            status_code=409,
            detail="Only an active organisation can be suspended.",
        )
    organisation.is_active = False
    if onboarding is not None:
        onboarding.status = "suspended"
    suspended_at = datetime.now(UTC)

    # Revoke all tenant refresh sessions in the same transaction as suspension.
    # Refresh rotation locks the organisation before locking its token family,
    # preserving a consistent lock order with this operation.
    _revoke_organisation_sessions(
        db,
        organisation_id,
        revoked_at=suspended_at,
    )

    open_invitations = db.scalars(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.organisation_id == organisation_id,
            OrganisationInvitation.accepted_at.is_(None),
            OrganisationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    for invitation in open_invitations:
        invitation.revoked_at = suspended_at
        invitation.revoked_by_user_id = actor.id
        invitation.revocation_reason = "tenant_suspended"
        db.add(
            AuditEvent(
                actor_user_id=actor.id,
                organisation_id=organisation_id,
                event_type="tenant.invitation_revoked",
                target_type="invitation",
                target_id=str(invitation.id),
                details={
                    "action": "tenant.invitation_revoked",
                    "outcome": "success",
                    "reason": "tenant_suspended",
                },
            )
        )
    _platform_audit_event(
        db,
        actor,
        event_type="platform.organisation_suspended",
        target_type="organisation",
        target_id=str(organisation_id),
        reason_code=body.reason_code,
    )
    db.commit()
    return {"organisation_id": str(organisation_id), "status": "suspended", "is_active": False}


@app.post("/platform/organisations/{organisation_id}/reactivate")
def reactivate_platform_organisation(
    organisation_id: UUID,
    body: TenantReactivateRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_SUSPEND)
    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    onboarding = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation_id)
        .with_for_update()
    )
    if onboarding is not None and onboarding.status not in {"suspended", "active"}:
        raise HTTPException(
            status_code=409,
            detail="Only a suspended organisation can be reactivated.",
        )
    organisation.is_active = True
    if onboarding is not None:
        onboarding.status = "active"
    _platform_audit_event(
        db,
        actor,
        event_type="platform.organisation_reactivated",
        target_type="organisation",
        target_id=str(organisation_id),
        reason_code=body.reason_code,
    )
    db.commit()
    return {"organisation_id": str(organisation_id), "status": "active", "is_active": True}


@app.get("/platform/users/roles")
def list_platform_role_holders(
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.PLATFORM_ROLES_ASSIGN)
    rows = db.execute(
        select(PlatformRoleAssignment, User)
        .join(User, User.id == PlatformRoleAssignment.user_id)
        .order_by(User.email, PlatformRoleAssignment.role)
    ).all()
    return {
        "count": len(rows),
        "assignments": [
            {
                "id": str(assignment.id),
                "user_id": str(user.id),
                "email": user.email,
                "role": assignment.role.value if isinstance(assignment.role, PlatformRole) else str(assignment.role),
                "assigned_at": assignment.created_at.isoformat(),
            }
            for assignment, user in rows
        ],
    }


@app.delete("/platform/users/{user_id}/roles/{role}")
def revoke_platform_role(
    user_id: UUID,
    role: PlatformRole,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.PLATFORM_ROLES_ASSIGN)
    # Serialize super-administrator revocations across transactions. PostgreSQL's
    # transaction-scoped advisory lock prevents two concurrent requests from each
    # observing the other administrator and jointly removing the final operator.
    if role == PlatformRole.SUPER_ADMINISTRATOR:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": 731904271})
        else:
            # SQLite ignores FOR UPDATE, but this keeps the same query path in API tests.
            db.scalar(select(User.id).where(User.id == actor.id).with_for_update())
        legacy_super_admin_ids = select(User.id).where(
            User.is_active.is_(True), User.is_platform_admin.is_(True)
        )
        assigned_super_admin_ids = (
            select(PlatformRoleAssignment.user_id)
            .join(User, User.id == PlatformRoleAssignment.user_id)
            .where(
                User.is_active.is_(True),
                PlatformRoleAssignment.role == PlatformRole.SUPER_ADMINISTRATOR.value,
            )
        )
        active_super_admin_ids = set(db.scalars(
            select(User.id)
            .where(or_(User.id.in_(legacy_super_admin_ids), User.id.in_(assigned_super_admin_ids)))
            .order_by(User.id)
            .with_for_update(of=User)
        ).all())
        if user_id in active_super_admin_ids and len(active_super_admin_ids) <= 1:
            raise HTTPException(
                status_code=409,
                detail="The last active platform super administrator cannot be revoked.",
            )

    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(status_code=404, detail="User was not found.")
    if target.is_platform_admin is True:
        raise HTTPException(
            status_code=409,
            detail="This user has the legacy platform administrator flag; revoke that flag through the reviewed identity migration first.",
        )
    assignment = db.scalar(
        select(PlatformRoleAssignment)
        .where(
            PlatformRoleAssignment.user_id == user_id,
            PlatformRoleAssignment.role == role.value,
        )
        .with_for_update()
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Platform role assignment was not found.")
    db.delete(assignment)
    db.add(
        AuditEvent(
            actor_user_id=actor.id,
            organisation_id=None,
            event_type="platform.role_revoked",
            target_type="user",
            target_id=str(user_id),
            details={"action": "platform.role_revoked", "outcome": "success", "role": role.value},
        )
    )
    db.commit()
    return {"user_id": str(user_id), "role": role.value, "revoked": True}


@app.get("/platform/audit/events")
def list_platform_audit_events(
    limit: int = Query(default=100, ge=1, le=250),
    before: datetime | None = None,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.AUDIT_READ)
    statement = select(AuditEvent)
    if before is not None:
        statement = statement.where(AuditEvent.occurred_at < before)
    events = db.scalars(
        statement.order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit)
    ).all()
    return {
        "count": len(events),
        "events": [
            {
                "id": str(event.id),
                "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                "organisation_id": str(event.organisation_id) if event.organisation_id else None,
                "event_type": event.event_type,
                "target_type": event.target_type if event.target_type not in {"document", "chunk", "query"} else "tenant_operation",
                "target_id": event.target_id if event.target_type not in {"document", "chunk", "query"} else None,
                "occurred_at": event.occurred_at.isoformat(),
                "details": _safe_platform_audit_details(event.details),
            }
            for event in events
        ],
    }


@app.get("/platform/users")
def search_platform_users(
    q: str = Query(min_length=2, max_length=320),
    limit: int = Query(default=25, ge=1, le=50),
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Search users for role assignment without exposing credential material."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.PLATFORM_ROLES_ASSIGN)

    needle = q.strip().lower()
    if len(needle) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query must contain at least two non-space characters.",
        )

    rows = db.execute(
        select(User.id, User.email, User.is_active)
        .where(User.email.ilike(f"%{needle}%"))
        .order_by(User.email)
        .limit(limit)
    ).all()

    return {
        "count": len(rows),
        "users": [
            {"id": str(user_id), "email": email, "is_active": is_active}
            for user_id, email, is_active in rows
        ],
    }


@app.post("/platform/users/roles", status_code=status.HTTP_201_CREATED)
def assign_platform_role(
    body: PlatformRoleAssignmentRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Assign a built-in platform role; only a super administrator may grant roles."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.PLATFORM_ROLES_ASSIGN)
    target = db.get(User, body.user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User was not found.")
    existing = db.scalar(select(PlatformRoleAssignment).where(
        PlatformRoleAssignment.user_id == target.id,
        PlatformRoleAssignment.role == body.role.value,
    ))
    if existing is not None:
        return {"user_id": str(target.id), "role": body.role.value, "already_assigned": True}
    assignment = PlatformRoleAssignment(
        user_id=target.id, role=body.role.value, assigned_by_user_id=actor.id,
    )
    db.add(assignment)
    db.add(AuditEvent(
        actor_user_id=actor.id, event_type="platform_role_assigned", target_type="user",
        target_id=str(target.id), details={"action": "platform_role_assigned", "outcome": "success", "role": body.role.value},
    ))
    db.commit()
    return {"user_id": str(target.id), "role": body.role.value, "already_assigned": False}


@app.get("/platform/organisations")
def list_platform_organisations(
    limit: int = Query(default=100, ge=1, le=250),
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """List platform tenant lifecycle records for authorized platform operators."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_READ)
    rows = db.execute(
        select(Organisation, TenantOnboarding)
        .outerjoin(TenantOnboarding, TenantOnboarding.organisation_id == Organisation.id)
        .order_by(Organisation.created_at.desc(), Organisation.id.desc())
        .limit(limit)
    ).all()
    return {
        "count": len(rows),
        "organisations": [
            {
                "id": str(organisation.id),
                "name": organisation.name,
                "slug": organisation.slug,
                "is_active": organisation.is_active,
                "status": onboarding.status if onboarding is not None else ("active" if organisation.is_active else "suspended"),
                "initial_admin_email": onboarding.initial_admin_email if onboarding is not None else None,
                "provisioning_attempts": onboarding.provisioning_attempts if onboarding is not None else 0,
                "provisioning_started_at": onboarding.provisioning_started_at.isoformat() if onboarding is not None and onboarding.provisioning_started_at else None,
                "provisioning_error_code": onboarding.provisioning_error_code if onboarding is not None else None,
                "created_at": organisation.created_at.isoformat() if organisation.created_at else None,
            }
            for organisation, onboarding in rows
        ],
    }


@app.post("/platform/organisations", status_code=status.HTTP_201_CREATED)
def create_platform_tenant(
    body: PlatformOrganisationCreateRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Create an inactive tenant pending explicit approval; platform admins only."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_CREATE)
    if idempotency_key is None or not idempotency_key.strip() or len(idempotency_key) > 200:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid Idempotency-Key header is required.",
        )
    try:
        result = create_platform_organisation(
            db,
            actor_user_id=actor.id,
            name=body.name,
            slug=body.slug,
            initial_admin_email=body.initial_admin_email,
            idempotency_key=idempotency_key,
        )
    except TenantOnboardingConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from None
    except Exception as exc:
        logger.error("Platform tenant creation failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant creation could not be completed. Retry with the same Idempotency-Key.",
        ) from None

    return {
        "organisation_id": str(result.organisation_id),
        "name": result.name,
        "slug": result.slug,
        "status": result.status,
        "initial_admin_email": result.initial_admin_email,
        "provisioning_attempts": result.provisioning_attempts,
        "idempotent_replay": result.idempotent_replay,
        "normal_access_enabled": result.status == "active",
        "request_id": str(uuid4()),
    }


@app.post("/platform/organisations/{organisation_id}/initial-admin-invitation", status_code=status.HTTP_201_CREATED)
def issue_initial_admin_invitation(
    organisation_id: UUID,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Issue the single activation invitation after approval and provisioning."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_APPROVE)
    if not _invitation_tokens_may_be_returned():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Invitation delivery is not configured. No invitation was created. "
                "Configure an outbound email provider before production use."
            ),
        )

    organisation = db.scalar(
        select(Organisation).where(Organisation.id == organisation_id).with_for_update()
    )
    if organisation is None:
        raise HTTPException(status_code=404, detail="Organisation was not found.")
    onboarding = db.scalar(
        select(TenantOnboarding)
        .where(TenantOnboarding.organisation_id == organisation_id)
        .with_for_update()
    )
    if (
        organisation.is_active
        or onboarding is None
        or onboarding.status != "pending_admin"
        or onboarding.provisioning_completed_at is None
        or onboarding.approved_by_user_id is None
        or onboarding.initial_admin_invitation_accepted_at is not None
    ):
        raise HTTPException(status_code=409, detail="Tenant is not ready for initial administrator invitation.")

    email = onboarding.initial_admin_email
    _assert_invitation_domain_allowed(db, organisation_id, email)
    current_initial_admin = db.scalars(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.organisation_id == organisation_id,
            OrganisationInvitation.purpose == "initial_admin",
            OrganisationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    if any(item.accepted_at is not None for item in current_initial_admin):
        raise HTTPException(status_code=409, detail="An initial administrator invitation has already been accepted.")

    now = datetime.now(UTC)
    for old in current_initial_admin:
        expires_at = old.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at > now:
            raise HTTPException(status_code=409, detail="A current initial administrator invitation already exists.")
        old.revoked_at = now
        old.revocation_reason = "expired"
        old.revoked_by_user_id = None
        old.superseded_by_id = None

    # A legacy 0007 invitation has no purpose column, so it correctly migrates
    # as a member invitation even when its recipient happens to be the pending
    # initial administrator. Close any such open invitation for this recipient
    # before inserting the purpose-specific initial-admin invitation. A live
    # invitation is superseded; an already-expired one is marked expired.
    invitation_id = uuid4()
    open_for_recipient = db.scalars(
        select(OrganisationInvitation)
        .where(
            OrganisationInvitation.organisation_id == organisation_id,
            OrganisationInvitation.recipient_email == email,
            OrganisationInvitation.accepted_at.is_(None),
            OrganisationInvitation.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    for old in open_for_recipient:
        expires_at = old.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        old.revoked_at = now
        old.revoked_by_user_id = None
        if expires_at > now:
            old.revocation_reason = "superseded"
            old.superseded_by_id = invitation_id
        else:
            old.revocation_reason = "expired"
            old.superseded_by_id = None
    if current_initial_admin or open_for_recipient:
        db.flush()

    raw_token = secrets.token_urlsafe(32)
    invitation = OrganisationInvitation(
        id=invitation_id,
        organisation_id=organisation_id,
        recipient_email=email,
        role=Role.ORGANISATION_ADMINISTRATOR.value,
        purpose="initial_admin",
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        invited_by_user_id=actor.id,
        expires_at=now + timedelta(days=7),
    )
    db.add(invitation)
    db.flush()
    onboarding.initial_admin_invitation_id = invitation.id
    _platform_audit_event(
        db,
        actor,
        event_type="tenant_initial_admin_invitation_issued",
        target_type="organisation",
        target_id=str(organisation_id),
        reason_code="initial_admin_invitation",
    )
    db.commit()
    return {
        "id": str(invitation.id),
        "organisation_id": str(organisation_id),
        "recipient_email": email,
        "purpose": "initial_admin",
        "invitation_token": raw_token,
        "expires_at": invitation.expires_at.isoformat(),
    }


@app.post("/platform/organisations/{organisation_id}/approve-provisioning", status_code=status.HTTP_200_OK)
def approve_platform_tenant_provisioning(
    organisation_id: UUID,
    body: ApprovePlatformOrganisationProvisioningRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Approve a pending tenant and begin idempotent resource provisioning."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.ORGANISATIONS_APPROVE)
    try:
        result = approve_and_provision_platform_organisation(
            db,
            actor_user_id=actor.id,
            organisation_id=organisation_id,
            approval_reason=body.approval_reason,
            provision_workspace=lambda tenant_id: tenant_workspaces.workspace_for(tenant_id),
        )
    except TenantOnboardingConflict as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in message else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from None
    except Exception as exc:
        logger.error("Platform tenant approval/provisioning failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant approval could not be completed.",
        ) from None
    return {
        "organisation_id": str(result.organisation_id),
        "status": result.status,
        "provisioning_attempts": result.provisioning_attempts,
        "normal_access_enabled": result.status == "active",
        "idempotent_replay": result.idempotent_replay,
        "request_id": str(uuid4()),
    }


@app.post("/platform/organisations/{organisation_id}/provisioning/retry", status_code=status.HTTP_200_OK)
def retry_platform_tenant_provisioning(
    organisation_id: UUID,
    body: ProvisioningRetryRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Retry failed provisioning after a platform administrator reviews the reason."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.PROVISIONING_RETRY)
    try:
        result = retry_platform_organisation_provisioning(
            db,
            actor_user_id=actor.id,
            organisation_id=organisation_id,
            reason=body.reason,
            provision_workspace=lambda tenant_id: tenant_workspaces.workspace_for(tenant_id),
        )
    except TenantOnboardingConflict as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in message else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from None
    except Exception as exc:
        logger.error("Platform tenant provisioning retry failed (%s).", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Tenant provisioning retry could not be completed.",
        ) from None
    return {
        "organisation_id": str(result.organisation_id),
        "status": result.status,
        "provisioning_attempts": result.provisioning_attempts,
        "normal_access_enabled": result.status == "active",
        "request_id": str(uuid4()),
    }


@app.post("/platform/organisations/{organisation_id}/provisioning/recover", status_code=status.HTTP_200_OK)
def recover_platform_tenant_provisioning(
    organisation_id: UUID,
    body: ProvisioningRecoveryRequest,
    context: AuthenticatedContext = Depends(get_authenticated_context),
    db: Session = Depends(get_auth_db),
):
    """Mark an expired in-flight attempt failed; a separate retry starts work again."""
    actor = db.get(User, context.principal.user_id)
    _require_platform_permission(db, actor, context, PlatformPermission.PROVISIONING_RECOVER)
    try:
        result = recover_stale_platform_organisation_provisioning(
            db, actor_user_id=actor.id, organisation_id=organisation_id, reason=body.reason,
        )
    except TenantOnboardingConflict as exc:
        message = str(exc)
        code = status.HTTP_404_NOT_FOUND if "not found" in message else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=code, detail=message) from None
    return {"organisation_id": str(result.organisation_id), "status": result.status, "provisioning_attempts": result.provisioning_attempts, "request_id": str(uuid4())}


@app.get("/health")
def health_check():
    """Minimal public liveness probe; it exposes no tenant information."""
    return {"status": "ok"}


@app.get("/tenant/status")
def tenant_status(
    context: AuthenticatedContext = Depends(require_permission(Permission.DOCUMENTS_READ)),
):
    workspace = _workspace(context)
    with tenant_workspace_lock(workspace, write=False):
        documents = workspace.read_manifest()
        return {
            "organisation_id": str(context.principal.organisation_id),
            "document_count": len(workspace.knowledge_base.documents),
            "chunk_count": len(workspace.knowledge_base.chunks),
            "failed_document_count": sum(
                1 for record in documents.values() if record.get("status") == "failed"
            ),
        }


@app.get("/documents")
def list_documents(
    context: AuthenticatedContext = Depends(require_permission(Permission.DOCUMENTS_READ)),
):
    workspace = _workspace(context)
    with tenant_workspace_lock(workspace, write=False):
        documents = [public_record(record) for record in workspace.knowledge_base.list_documents()]
    return {"count": len(documents), "documents": documents}


@app.post("/documents", status_code=201)
def upload_document(
    file: UploadFile = File(...),
    context: AuthenticatedContext = Depends(require_permission(Permission.DOCUMENTS_UPLOAD)),
    db: Session = Depends(get_auth_db),
):
    workspace = _workspace(context)
    filename = Path(file.filename or "").name
    document_id = str(uuid4())
    audit_event = _start_audit_event(
        db,
        context,
        event_type="document.upload",
        target_type="document",
        target_id=document_id,
    )
    audit_outcome_attempted = False
    original_manifest = None
    document_added = False
    stored_path = resolve_stored_path(workspace.upload_directory, document_id)
    try:
        if len(filename) > MAX_FILENAME_CHARACTERS:
            raise HTTPException(status_code=422, detail="Filename must be 255 characters or fewer.")
        if not filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Only PDF files are supported.")
        total_bytes = 0
        header = b""
        with stored_path.open("xb") as destination:
            while chunk := file.file.read(1024 * 1024):
                if not header:
                    header = chunk[:5]
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="PDF exceeds the 25 MB upload limit.")
                destination.write(chunk)
        if header != b"%PDF-":
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid PDF.")

        digest = sha256_file(stored_path)
        with tenant_workspace_lock(workspace, write=True):
            current = workspace.read_manifest()
            original_manifest = current
            duplicate = find_duplicate_document(
                file_digest=digest,
                documents=current,
                upload_directory=workspace.upload_directory,
            )
            if duplicate is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Identical PDF content is already indexed.",
                        "existing_document": public_record(duplicate),
                    },
                )
            record = workspace.knowledge_base.add_pdf(stored_path, document_id=document_id)
            document_added = True
            _set_original_filename(workspace, document_id, filename)
            record = workspace.knowledge_base.documents[document_id]
            record.update({"filename": filename, "status": "indexed", "sha256": digest})
            try:
                workspace.write_manifest({**current, document_id: manifest_record(document_id, record)})
            except Exception:
                workspace.knowledge_base.delete_document(document_id)
                document_added = False
                raise
            audit_outcome_attempted = True
            _finish_audit_event(db, audit_event, outcome="success")
        return {"message": "Document indexed and registered successfully.", "document": public_record(record)}
    except HTTPException as exc:
        if document_added:
            try:
                with tenant_workspace_lock(workspace, write=True):
                    workspace.knowledge_base.delete_document(document_id)
                    if original_manifest is not None:
                        workspace.write_manifest(original_manifest)
            except Exception as cleanup_error:
                logger.error("Tenant upload rollback failed (%s).", type(cleanup_error).__name__)
        stored_path.unlink(missing_ok=True)
        if not audit_outcome_attempted:
            audit_outcome_attempted = True
            _finish_audit_event(db, audit_event, outcome="failure", reason=f"http_{exc.status_code}")
        raise
    except ValueError as exc:
        # Deliberate content validation from PDF loading; never echo its message.
        if document_added:
            try:
                with tenant_workspace_lock(workspace, write=True):
                    workspace.knowledge_base.delete_document(document_id)
                    if original_manifest is not None:
                        workspace.write_manifest(original_manifest)
            except Exception as cleanup_error:
                logger.error("Tenant upload rollback failed (%s).", type(cleanup_error).__name__)
        stored_path.unlink(missing_ok=True)
        if not audit_outcome_attempted:
            audit_outcome_attempted = True
            _finish_audit_event(db, audit_event, outcome="failure", reason="invalid_document")
        raise HTTPException(
            status_code=400,
            detail="The PDF could not be processed. Upload a text-based PDF.",
        ) from exc
    except Exception as exc:
        if document_added:
            try:
                with tenant_workspace_lock(workspace, write=True):
                    workspace.knowledge_base.delete_document(document_id)
                    if original_manifest is not None:
                        workspace.write_manifest(original_manifest)
            except Exception as cleanup_error:
                logger.error("Tenant upload rollback failed (%s).", type(cleanup_error).__name__)
        stored_path.unlink(missing_ok=True)
        if not audit_outcome_attempted:
            audit_outcome_attempted = True
            _finish_audit_event(db, audit_event, outcome="failure", reason="internal_error")
        raise _server_error(500, "Document upload or indexing failed.", exc, "Tenant document upload") from exc
    finally:
        file.file.close()


@app.post("/query")
def query(
    request: QueryRequest,
    context: AuthenticatedContext = Depends(require_permission(Permission.DOCUMENTS_QUERY)),
    db: Session = Depends(get_auth_db),
):
    workspace = _workspace(context)
    audit_event = _start_audit_event(
        db,
        context,
        event_type="knowledge.query",
        target_type="knowledge_query",
    )
    with tenant_workspace_lock(workspace, write=False):
        try:
            result = workspace.get_pipeline().query(
                question=request.question,
                top_k=request.top_k,
                tenant_id=str(context.principal.organisation_id),
            )
        except Exception as exc:
            # Pipeline ValueErrors are configuration/internal faults (e.g. a missing LLM key),
            # not client input errors; request validation already happened in QueryRequest.
            _finish_audit_event(db, audit_event, outcome="failure", reason="query_error")
            raise _server_error(500, "Knowledge query failed.", exc, "Tenant knowledge query") from exc
    _finish_audit_event(db, audit_event, outcome="success")
    return result


@app.get("/documents/{document_id}/file")
def download_document(
    document_id: str,
    context: AuthenticatedContext = Depends(require_permission(Permission.DOCUMENTS_READ)),
):
    workspace = _workspace(context)
    try:
        path = resolve_stored_path(workspace.upload_directory, document_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found.") from None
    with tenant_workspace_lock(workspace, write=False):
        if document_id not in workspace.knowledge_base.documents or not path.is_file():
            raise HTTPException(status_code=404, detail="Document not found.")
        filename = workspace.knowledge_base.documents[document_id].get("filename", "document.pdf")
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=Path(filename).name,
        content_disposition_type="attachment",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.delete("/documents/{document_id}")
def delete_document(
    document_id: str,
    context: AuthenticatedContext = Depends(require_permission(Permission.DOCUMENTS_DELETE)),
    db: Session = Depends(get_auth_db),
):
    workspace = _workspace(context)
    try:
        source_path = resolve_stored_path(workspace.upload_directory, document_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Document not found.") from None
    with tenant_workspace_lock(workspace, write=True):
        record = workspace.knowledge_base.documents.get(document_id)
        current = workspace.read_manifest()
        saved = current.get(document_id)
        failed_restore = record is None and isinstance(saved, dict) and saved.get("status") == "failed"
        if record is None and not failed_restore:
            raise HTTPException(status_code=404, detail="Document not found.")
        audit_event = _start_audit_event(
            db,
            context,
            event_type="document.delete",
            target_type="document",
            target_id=document_id,
        )
        try:
            workspace.write_manifest({key: value for key, value in current.items() if key != document_id})
            if failed_restore:
                deleted_record = {"filename": saved.get("filename", source_path.name), "chunk_count": 0}
            else:
                deleted_record = workspace.knowledge_base.delete_document(document_id)
            try:
                source_path.unlink(missing_ok=True)
                file_deleted = True
            except OSError:
                file_deleted = False
            _finish_audit_event(
                db,
                audit_event,
                outcome="success" if file_deleted else "partial",
                reason=None if file_deleted else "file_cleanup_required",
            )
            return {
                "message": "Document removed from the active organisation workspace.",
                "document_id": document_id,
                "filename": deleted_record["filename"],
                "chunks_removed": deleted_record["chunk_count"],
                "file_deleted": file_deleted,
                "cleanup_required": not file_deleted,
            }
        except HTTPException:
            raise
        except Exception as exc:
            _finish_audit_event(db, audit_event, outcome="failure", reason="delete_error")
            raise _server_error(500, "Document deletion failed.", exc, "Tenant document deletion") from exc


def _set_original_filename(workspace: TenantWorkspace, document_id: str, filename: str) -> None:
    set_original_filename(workspace.knowledge_base, document_id, filename)
