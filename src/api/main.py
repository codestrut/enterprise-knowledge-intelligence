"""FastAPI application with managed authentication and tenant-scoped RAG."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.api.document_fingerprints import find_duplicate_document, sha256_file
from src.api.document_records import manifest_record, public_record, resolve_stored_path
from src.api.shared_inference import SharedGroundingEvaluator, SharedReranker
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
from src.auth.permissions import Permission
from src.auth.models import AuditEvent, Organisation, OrganisationMembership, User
from src.auth.passwords import MAX_PASSWORD_CODEPOINTS
from src.auth.throttling import FailureThrottle
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
    organisation: OrganisationProfile
    role: str
    permissions: list[str]


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
        "organisation_id": str(grant.principal.organisation_id),
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
    return CurrentUserProfile(
        email=email,
        organisation=OrganisationProfile(id=organisation_id, name=organisation_name),
        role=principal.role.value,
        permissions=sorted(permission.value for permission in principal.permissions),
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


def _workspace(context: AuthenticatedContext) -> TenantWorkspace:
    return tenant_workspaces.workspace_for(context.principal.organisation_id)


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
