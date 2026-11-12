"""Production-path capability tests for Phase 1 backend work.

These tests deliberately call the real authentication services, database models,
FastAPI dependency graph, and registered application routes. They are intended to
be written before Phase 1 endpoint implementation; failures identify capabilities
that are not yet wired into the application.

Inference/model modules are replaced only while importing the API module because
these tests do not execute embedding or generation code. The actual authentication,
permission, database, and API modules remain unmocked.
"""

from __future__ import annotations

import hashlib
import importlib
import re
import secrets
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.auth.access_tokens import decode_access_token, issue_access_token
from src.auth.models import (
    AuditEvent,
    Base,
    Organisation,
    OrganisationInvitation,
    OrganisationSettings,
    OrganisationMembership,
    RefreshSessionRecord,
    TenantOnboarding,
    User,
)
from src.auth.passwords import hash_password
from src.auth.permissions import Permission, Role, permissions_for_role
from src.api.phase1_admin_contracts import (
    AcceptInvitationRequest,
    TenantMemberInviteRequest,
    TenantSettingsUpdateRequest,
)
from src.auth.service import login_platform_operator
from src.api.rwlock import ReadWriteLock


PASSWORD = "Phase1-Valid-Password-2026!"
SIGNING_SECRET = "phase1-capability-test-secret-at-least-32-bytes"


class _FakeKnowledgeBase:
    def __init__(self, embedder=None, reranker=None):
        self.embedder = embedder
        self.documents = {}
        self.chunks = []

    def list_documents(self):
        return []


class _FakeWorkspace:
    def __init__(self, organisation_id: UUID, root: Path):
        self.organisation_id = organisation_id
        self.root = root
        self.upload_directory = root / "uploads"
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = root / "documents_manifest.json"
        self.knowledge_base = _FakeKnowledgeBase()
        self.lock = ReadWriteLock()

    def read_manifest(self):
        return {}


class _FakeRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._workspaces: dict[UUID, _FakeWorkspace] = {}

    def workspace_for(self, organisation_id: UUID):
        if organisation_id not in self._workspaces:
            self._workspaces[organisation_id] = _FakeWorkspace(
                organisation_id, self.root / str(organisation_id)
            )
        return self._workspaces[organisation_id]


def _import_api_without_inference_dependencies():
    """Import the real FastAPI app without loading heavyweight RAG model packages."""
    stub_specs = {
        "src.knowledge_base": ("KnowledgeBase", _FakeKnowledgeBase),
        "src.generation.grounding_evaluator": (
            "GroundingEvaluator",
            type("GroundingEvaluator", (), {"__init__": lambda self, *a, **k: None}),
        ),
        "src.rag_pipeline": (
            "RAGPipeline",
            type("RAGPipeline", (), {"__init__": lambda self, *a, **k: None}),
        ),
    }
    inserted: list[str] = []
    for module_name, (symbol_name, symbol) in stub_specs.items():
        if module_name not in sys.modules:
            stub = types.ModuleType(module_name)
            setattr(stub, symbol_name, symbol)
            sys.modules[module_name] = stub
            inserted.append(module_name)

    try:
        return importlib.import_module("src.api.main")
    finally:
        # main.py has retained the imported class references. Restore sys.modules
        # so unrelated tests can import the actual RAG modules normally.
        for module_name in inserted:
            sys.modules.pop(module_name, None)


@pytest.fixture
def phase1_api_environment(monkeypatch, tmp_path):
    api = _import_api_without_inference_dependencies()
    monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", SIGNING_SECRET)
    monkeypatch.setattr(api, "tenant_workspaces", _FakeRegistry(tmp_path / "tenant-data"))

    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'phase1-auth.sqlite'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    identities: dict[str, dict[str, object]] = {}

    with Session(engine) as db:
        alpha = Organisation(name="Tenant Alpha", slug="tenant-alpha")
        beta = Organisation(name="Tenant Beta", slug="tenant-beta")
        db.add_all([alpha, beta])
        db.flush()

        identity_specs = [
            ("admin-a@example.test", alpha, Role.ORGANISATION_ADMINISTRATOR, False),
            ("admin-a2@example.test", alpha, Role.ORGANISATION_ADMINISTRATOR, False),
            ("reader-a@example.test", alpha, Role.READER, False),
            ("contributor-a@example.test", alpha, Role.CONTRIBUTOR, False),
            ("admin-b@example.test", beta, Role.ORGANISATION_ADMINISTRATOR, False),
            ("platform-admin@example.test", alpha, Role.ORGANISATION_ADMINISTRATOR, True),
        ]
        for email, organisation, role, is_platform_admin in identity_specs:
            user = User(
                email=email,
                password_hash=hash_password(PASSWORD),
                is_active=True,
                is_platform_admin=is_platform_admin,
            )
            membership = OrganisationMembership(
                user=user,
                organisation=organisation,
                role=role,
                is_active=True,
            )
            db.add_all([user, membership])
            identities[email] = {
                "user": user,
                "organisation": organisation,
                "membership": membership,
            }

        platform_only = User(
            email="platform-only@example.test",
            password_hash=hash_password(PASSWORD),
            is_active=True,
            is_platform_admin=True,
        )
        db.add(platform_only)
        identities[platform_only.email] = {
            "user": platform_only,
            "organisation": None,
            "membership": None,
        }
        db.flush()

        creator_id = identities["admin-a@example.test"]["user"].id
        for organisation, initial_admin_email in (
            (alpha, "admin-a@example.test"),
            (beta, "admin-b@example.test"),
        ):
            db.add(
                TenantOnboarding(
                    organisation_id=organisation.id,
                    status="active",
                    initial_admin_email=initial_admin_email,
                    idempotency_key=str(uuid4()),
                    request_fingerprint="phase1-test-fingerprint",
                    created_by_user_id=creator_id,
                    provisioning_attempts=1,
                )
            )
        db.commit()

        for identity in identities.values():
            db.refresh(identity["user"])
            if identity["organisation"] is not None:
                db.refresh(identity["organisation"])

    def _override_db():
        with Session(engine) as db:
            yield db

    previous_overrides = dict(api.app.dependency_overrides)
    api.app.dependency_overrides[api.get_auth_db] = _override_db
    client = TestClient(api.app)

    yield {
        "api": api,
        "client": client,
        "engine": engine,
        "identities": identities,
    }

    api.app.dependency_overrides.clear()
    api.app.dependency_overrides.update(previous_overrides)
    engine.dispose()


def _tenant_login(environment, email: str = "admin-a@example.test"):
    response = environment["client"].post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body


def _platform_service_grant(environment):
    with Session(environment["engine"]) as db:
        return login_platform_operator(db, "platform-only@example.test", PASSWORD)


def _set_onboarding_status(environment, status_value: str):
    organisation_id = environment["identities"]["admin-a@example.test"]["organisation"].id
    with Session(environment["engine"]) as db:
        onboarding = db.scalar(
            select(TenantOnboarding).where(
                TenantOnboarding.organisation_id == organisation_id
            )
        )
        assert onboarding is not None
        onboarding.status = status_value
        db.commit()
    return organisation_id



# ---------------------------------------------------------------------------
# Real Phase 1 schemas and database constraints.
# ---------------------------------------------------------------------------


def test_invitation_model_normalizes_recipient_and_persists_only_hash(
    phase1_api_environment,
):
    environment = phase1_api_environment
    actor_id = environment["identities"]["admin-a@example.test"]["user"].id
    organisation_id = environment["identities"]["admin-a@example.test"]["organisation"].id
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    with Session(environment["engine"]) as db:
        invitation = OrganisationInvitation(
            organisation_id=organisation_id,
            recipient_email="  Colleague@Example.Test  ",
            role=Role.CONTRIBUTOR.value,
            token_hash=token_hash,
            invited_by_user_id=actor_id,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        db.add(invitation)
        db.commit()
        assert invitation.recipient_email == "colleague@example.test"
        assert invitation.token_hash == token_hash
        assert token not in invitation.token_hash


def test_invitation_database_constraint_rejects_platform_role(phase1_api_environment):
    environment = phase1_api_environment
    actor_id = environment["identities"]["admin-a@example.test"]["user"].id
    organisation_id = environment["identities"]["admin-a@example.test"]["organisation"].id

    with Session(environment["engine"]) as db:
        db.add(
            OrganisationInvitation(
                organisation_id=organisation_id,
                recipient_email="intruder@example.test",
                role="platform_super_administrator",
                token_hash=hashlib.sha256(b"not-a-real-invite").hexdigest(),
                invited_by_user_id=actor_id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_organisation_settings_database_constraint_enforces_timeout_bounds(
    phase1_api_environment,
):
    environment = phase1_api_environment
    organisation_id = environment["identities"]["admin-a@example.test"]["organisation"].id

    with Session(environment["engine"]) as db:
        db.add(
            OrganisationSettings(
                organisation_id=organisation_id,
                allowed_email_domains=["example.test"],
                session_idle_timeout_minutes=1441,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_phase1_invitation_and_settings_contracts_validate_real_inputs():
    invitation = TenantMemberInviteRequest(
        recipient_email=" Colleague@Example.Test ",
        role=Role.CONTRIBUTOR,
        message="Welcome",
    )
    assert invitation.recipient_email == "colleague@example.test"

    with pytest.raises(ValueError):
        TenantMemberInviteRequest(
            recipient_email="not-an-email",
            role=Role.READER,
        )

    accepted = AcceptInvitationRequest(
        token="one-time-secret-token",
        password=PASSWORD,
    )
    assert "one-time-secret-token" not in repr(accepted)

    settings = TenantSettingsUpdateRequest(
        allowed_email_domains=[" @Example.Test ", "partner.test", "example.test"],
        session_idle_timeout_minutes=120,
    )
    assert settings.allowed_email_domains == ["example.test", "partner.test"]
    assert settings.session_idle_timeout_minutes == 120

    with pytest.raises(ValueError):
        TenantSettingsUpdateRequest(session_idle_timeout_minutes=4)

# ---------------------------------------------------------------------------
# Existing production service capabilities (these should pass now).
# ---------------------------------------------------------------------------


def test_platform_login_service_creates_membershipless_hashed_refresh_session(
    phase1_api_environment,
):
    environment = phase1_api_environment
    grant = _platform_service_grant(environment)

    with Session(environment["engine"]) as db:
        record = db.scalar(
            select(RefreshSessionRecord).where(
                RefreshSessionRecord.family_id == grant.family_id
            )
        )
        assert record is not None
        assert record.membership_id is None
        assert record.user_id == grant.principal.user_id
        assert record.token_hash == hashlib.sha256(
            grant.refresh_token.encode("utf-8")
        ).hexdigest()
        assert grant.refresh_token not in record.token_hash

        access = issue_access_token(
            grant.principal, grant.family_id, secret=SIGNING_SECRET
        )
        claims = decode_access_token(access.token, secret=SIGNING_SECRET)
        from src.auth.dependencies import _revalidate_against_database

        resolved = _revalidate_against_database(db, claims)
        assert resolved.principal.user_id == grant.principal.user_id
        assert resolved.principal.permissions == frozenset()
        assert resolved.family_id == grant.family_id


def test_platform_only_session_cannot_read_tenant_documents(phase1_api_environment):
    environment = phase1_api_environment
    grant = _platform_service_grant(environment)
    access = issue_access_token(
        grant.principal, grant.family_id, secret=SIGNING_SECRET
    )

    response = environment["client"].get(
        "/documents", headers={"Authorization": f"Bearer {access.token}"}
    )
    assert response.status_code == 403


def test_platform_only_refresh_rotation_preserves_independent_scope(
    phase1_api_environment,
):
    environment = phase1_api_environment
    grant = _platform_service_grant(environment)
    response = environment["client"].post(
        "/auth/refresh",
        json={
            "refresh_token": grant.refresh_token,
            "rotation_key": secrets.token_urlsafe(32),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["permissions"] == []
    assert response.json()["role"] == Role.READER.value


# ---------------------------------------------------------------------------
# Missing/wrong production wiring (these are expected to fail until fixed).
# ---------------------------------------------------------------------------


def test_login_route_accepts_platform_operator_without_tenant_membership(
    phase1_api_environment,
):
    response = phase1_api_environment["client"].post(
        "/auth/login",
        json={"email": "platform-only@example.test", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["permissions"] == []


def test_auth_me_returns_platform_profile_without_fake_tenant_scope(
    phase1_api_environment,
):
    environment = phase1_api_environment
    grant = _platform_service_grant(environment)
    access = issue_access_token(
        grant.principal, grant.family_id, secret=SIGNING_SECRET
    )
    response = environment["client"].get(
        "/auth/me", headers={"Authorization": f"Bearer {access.token}"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["email"] == "platform-only@example.test"
    assert body["organisation"] is None
    assert body["platform_permissions"]


def test_suspended_onboarding_blocks_existing_access_token_even_when_org_flag_is_active(
    phase1_api_environment,
):
    environment = phase1_api_environment
    headers, _login = _tenant_login(environment)
    organisation_id = _set_onboarding_status(environment, "suspended")

    with Session(environment["engine"]) as db:
        organisation = db.get(Organisation, organisation_id)
        assert organisation is not None and organisation.is_active is True

    response = environment["client"].get("/documents", headers=headers)
    assert response.status_code == 403, response.text


def test_suspended_onboarding_blocks_new_password_login(phase1_api_environment):
    environment = phase1_api_environment
    _set_onboarding_status(environment, "suspended")
    response = environment["client"].post(
        "/auth/login",
        json={"email": "admin-a@example.test", "password": PASSWORD},
    )
    assert response.status_code in {401, 403}, response.text


def test_suspended_onboarding_blocks_refresh_of_existing_session(
    phase1_api_environment,
):
    environment = phase1_api_environment
    _headers, login = _tenant_login(environment)
    _set_onboarding_status(environment, "suspended")
    response = environment["client"].post(
        "/auth/refresh",
        json={
            "refresh_token": login["refresh_token"],
            "rotation_key": secrets.token_urlsafe(32),
        },
    )
    assert response.status_code in {401, 403}, response.text


@pytest.mark.parametrize("role", [Role.CONTRIBUTOR, Role.READER])
def test_non_admin_tenant_roles_cannot_manage_members_or_security(role):
    permissions = permissions_for_role(role)
    assert Permission.MEMBERS_MANAGE not in permissions
    assert Permission.AUTH_CONFIGURE not in permissions
    assert Permission.AUDIT_READ not in permissions


def test_organisation_administrator_retains_required_admin_permissions():
    permissions = permissions_for_role(Role.ORGANISATION_ADMINISTRATOR)
    assert {
        Permission.TENANT_READ,
        Permission.MEMBERS_MANAGE,
        Permission.AUTH_CONFIGURE,
        Permission.AUDIT_READ,
    }.issubset(permissions)


def test_tenant_read_permission_is_granted_to_every_tenant_role():
    for role in (
        Role.ORGANISATION_ADMINISTRATOR,
        Role.CONTRIBUTOR,
        Role.READER,
    ):
        assert Permission.TENANT_READ in permissions_for_role(role), role


def _normalise_route(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def test_phase1_tenant_and_platform_admin_routes_are_registered(
    phase1_api_environment,
):
    api = phase1_api_environment["api"]
    registered = {
        (method, _normalise_route(route.path))
        for route in api.app.routes
        if hasattr(route, "methods")
        for method in route.methods
    }
    required = {
        ("GET", "/tenant/overview"),
        ("GET", "/tenant/members"),
        ("PATCH", "/tenant/members/{}"),
        ("DELETE", "/tenant/members/{}"),
        ("POST", "/tenant/members/invitations"),
        ("GET", "/tenant/members/invitations"),
        ("DELETE", "/tenant/members/invitations/{}"),
        ("POST", "/auth/invitations/accept"),
        ("GET", "/tenant/settings"),
        ("PATCH", "/tenant/settings"),
        ("GET", "/platform/overview"),
        ("POST", "/platform/organisations/{}/suspend"),
        ("POST", "/platform/organisations/{}/reactivate"),
        ("GET", "/platform/users/roles"),
        ("DELETE", "/platform/users/{}/roles/{}"),
        ("GET", "/platform/audit/events"),
    }
    missing = sorted(required - registered)
    assert not missing, "Missing Phase 1 API routes:\n" + "\n".join(
        f"{method} {path}" for method, path in missing
    )


def test_platform_only_session_does_not_receive_tenant_membership_or_data_scope(
    phase1_api_environment,
):
    environment = phase1_api_environment
    grant = _platform_service_grant(environment)
    assert grant.principal.membership_id == UUID(int=0)
    assert grant.principal.organisation_id == UUID(int=0)
    assert not grant.principal.permissions

    with Session(environment["engine"]) as db:
        record = db.scalar(
            select(RefreshSessionRecord).where(
                RefreshSessionRecord.family_id == grant.family_id
            )
        )
        assert record is not None and record.membership_id is None
        assert db.scalar(
            select(OrganisationMembership.id).where(
                OrganisationMembership.user_id == grant.principal.user_id
            )
        ) is None
        assert db.scalar(
            select(AuditEvent.id).where(
                AuditEvent.actor_user_id == grant.principal.user_id,
                AuditEvent.event_type == "auth.platform_session_created",
            )
        ) is not None
