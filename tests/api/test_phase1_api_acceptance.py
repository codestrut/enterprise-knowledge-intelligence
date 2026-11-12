"""API acceptance tests for Phase 1 Core Governance, Tenant Admin, and Platform Admin."""

from __future__ import annotations

import types
import sys
from datetime import UTC, datetime, timedelta
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from src.auth.models import (
    Base,
    Organisation,
    OrganisationMembership,
    OrganisationInvitation,
    OrganisationSettings,
    RefreshSessionRecord,
    PlatformRoleAssignment,
    TenantOnboarding,
    User,
    AuditEvent,
)
from src.auth.passwords import hash_password
from src.api.rwlock import ReadWriteLock
from src.auth.permissions import Permission, PlatformPermission, PlatformRole, Role


VALID_PASSWORD = "Argon2id-Valid-Password-123456!"


class FakeKnowledgeBase:
    def __init__(self, embedder=None, reranker=None):
        self.documents = {}
        self.chunks = []
        self.embedder = embedder


class FakeWorkspace:
    def __init__(self, org_id: UUID, root: Path):
        self.organisation_id = org_id
        self.root = root
        self.upload_directory = root / "uploads"
        self.upload_directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = root / "documents_manifest.json"
        self.knowledge_base = FakeKnowledgeBase()
        self.lock = ReadWriteLock()

    def read_manifest(self):
        return {}


class FakeRegistry:
    def __init__(self, root: Path):
        self.root = root
        self._workspaces: dict[UUID, FakeWorkspace] = {}

    def workspace_for(self, org_id: UUID):
        if org_id not in self._workspaces:
            ws = FakeWorkspace(org_id, self.root / str(org_id))
            self._workspaces[org_id] = ws
        return self._workspaces[org_id]


@pytest.fixture
def api_environment(monkeypatch):
    grounding_module = types.ModuleType("src.generation.grounding_evaluator")
    grounding_module.GroundingEvaluator = type(
        "GroundingEvaluator", (), {"__init__": lambda self, *args, **kwargs: None}
    )
    knowledge_base_module = types.ModuleType("src.knowledge_base")
    knowledge_base_module.KnowledgeBase = FakeKnowledgeBase
    rag_pipeline_module = types.ModuleType("src.rag_pipeline")
    rag_pipeline_module.RAGPipeline = type(
        "RAGPipeline", (), {"__init__": lambda self, *args, **kwargs: None}
    )
    monkeypatch.setitem(sys.modules, "src.generation.grounding_evaluator", grounding_module)
    monkeypatch.setitem(sys.modules, "src.knowledge_base", knowledge_base_module)
    monkeypatch.setitem(sys.modules, "src.rag_pipeline", rag_pipeline_module)
    monkeypatch.setenv("EKIP_EXPOSE_INVITATION_TOKENS", "1")
    monkeypatch.setenv("EKIP_ENV", "test")
    import src.api.main as api

    temp_dir = TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    fake_registry = FakeRegistry(temp_path)
    monkeypatch.setattr(api, "tenant_workspaces", fake_registry)
    monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", "test-secret-at-least-32-bytes-long-1234567890")

    engine = create_engine(
        f"sqlite+pysqlite:///{temp_path / 'auth.sqlite'}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    identities = {}

    with Session(engine) as db:
        org_a = Organisation(name="Tenant Alpha", slug="tenant-alpha", is_active=True)
        org_b = Organisation(name="Tenant Beta", slug="tenant-beta", is_active=True)
        db.add_all([org_a, org_b])
        db.flush()

        specs = [
            ("admin-a@example.test", Role.ORGANISATION_ADMINISTRATOR, org_a, False),
            ("admin-a2@example.test", Role.ORGANISATION_ADMINISTRATOR, org_a, False),
            ("reader-a@example.test", Role.READER, org_a, False),
            ("contributor-a@example.test", Role.CONTRIBUTOR, org_a, False),
            ("admin-b@example.test", Role.ORGANISATION_ADMINISTRATOR, org_b, False),
            ("platform-admin@example.test", Role.READER, org_a, True),
        ]
        for email, role, organisation, platform in specs:
            user = User(
                email=email,
                password_hash=hash_password(VALID_PASSWORD),
                is_platform_admin=platform,
                is_active=True,
            )
            membership = OrganisationMembership(user=user, organisation=organisation, role=role, is_active=True)
            db.add_all([user, membership])
            identities[email] = {"user": user, "organisation": organisation, "membership": membership, "role": role}

        no_membership = User(
            email="platform-only@example.test",
            password_hash=hash_password(VALID_PASSWORD),
            is_platform_admin=True,
            is_active=True,
        )
        db.add(no_membership)
        identities[no_membership.email] = {"user": no_membership, "organisation": None, "role": None}
        db.flush()

        creator_user_id = identities["admin-a@example.test"]["user"].id
        onboarding_a = TenantOnboarding(
            organisation_id=org_a.id,
            status="active",
            initial_admin_email="admin-a@example.test",
            idempotency_key=str(uuid4()),
            request_fingerprint="fingerprint-a",
            created_by_user_id=creator_user_id,
            provisioning_attempts=1,
        )
        onboarding_b = TenantOnboarding(
            organisation_id=org_b.id,
            status="active",
            initial_admin_email="admin-b@example.test",
            idempotency_key=str(uuid4()),
            request_fingerprint="fingerprint-b",
            created_by_user_id=creator_user_id,
            provisioning_attempts=1,
        )
        db.add_all([onboarding_a, onboarding_b])
        db.commit()

        for identity in identities.values():
            db.refresh(identity["user"])
            if identity["organisation"] is not None:
                db.refresh(identity["organisation"])

    def override_db():
        with Session(engine) as db:
            yield db

    api.app.dependency_overrides[api.get_auth_db] = override_db
    client = TestClient(api.app)

    yield {
        "client": client,
        "engine": engine,
        "identities": identities,
        "api": api,
    }

    api.app.dependency_overrides.clear()
    temp_dir.cleanup()


def auth_headers(api_environment, email, *, auth_scope="tenant"):
    client = api_environment["client"]
    res = client.post("/auth/login", json={"email": email, "password": VALID_PASSWORD, "auth_scope": auth_scope})
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, res.json()


def test_invitation_token_exposure_fails_closed_for_unknown_or_missing_environment(
    api_environment, monkeypatch
):
    api = api_environment["api"]
    monkeypatch.setenv("EKIP_EXPOSE_INVITATION_TOKENS", "1")
    monkeypatch.setenv("EKIP_ENV", "staging")
    assert api._invitation_tokens_may_be_returned() is False

    monkeypatch.delenv("EKIP_ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert api._invitation_tokens_may_be_returned() is False


def test_disabled_user_is_not_counted_as_an_active_organisation_admin(api_environment):
    organisation_id = api_environment["identities"]["admin-a@example.test"]["organisation"].id
    disabled_user_id = api_environment["identities"]["admin-a@example.test"]["user"].id
    api = api_environment["api"]

    with Session(api_environment["engine"]) as db:
        disabled_user = db.get(User, disabled_user_id)
        disabled_user.is_active = False
        db.commit()

        # admin-a2 remains the only enabled administrator.
        assert api._active_admin_count(db, organisation_id) == 1


# ==============================================================================
# Tenant Overview
# ==============================================================================

def test_tenant_overview_permits_admin_and_denies_cross_tenant(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")
    res = client.get("/tenant/overview", headers=headers_a)
    assert res.status_code == 200
    data = res.json()
    assert data["organisation_name"] == "Tenant Alpha"
    assert data["member_count"] >= 4  # admin-a, admin-a2, reader-a, contributor-a


def test_tenant_overview_is_readable_by_reader_without_admin_capabilities(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "reader-a@example.test")
    res = client.get("/tenant/overview", headers=headers)
    assert res.status_code == 200
    assert res.json()["organisation_name"] == "Tenant Alpha"


# ==============================================================================
# Tenant Members & Concurrency-Safe Last Admin Protection
# ==============================================================================

def test_tenant_members_list_and_role_management(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")

    # List members
    res = client.get("/tenant/members", headers=headers_a)
    assert res.status_code == 200
    members = res.json()["members"]
    emails = {m["email"] for m in members}
    assert "admin-a@example.test" in emails
    assert "admin-b@example.test" not in emails  # Strict tenant isolation

    # Find admin-a2
    admin2 = next(m for m in members if m["email"] == "admin-a2@example.test")

    # Demote admin-a2 to contributor (allowed because admin-a is still active admin)
    demote_res = client.patch(
        f"/tenant/members/{admin2['id']}",
        json={"role": "contributor"},
        headers=headers_a,
    )
    assert demote_res.status_code == 200
    assert demote_res.json()["role"] == "contributor"

    # Now admin-a is the SOLE administrator. Attempting to demote admin-a must fail with 409
    admin1 = next(m for m in members if m["email"] == "admin-a@example.test")
    sole_demote = client.patch(
        f"/tenant/members/{admin1['id']}",
        json={"role": "reader"},
        headers=headers_a,
    )
    assert sole_demote.status_code == 409
    assert "last active organisation administrator" in sole_demote.json()["detail"].lower()

    # Attempting to delete sole admin also fails with 409
    sole_delete = client.delete(
        f"/tenant/members/{admin1['id']}",
        headers=headers_a,
    )
    assert sole_delete.status_code == 409


# ==============================================================================
# Invitations Lifecycle: Send, Inspect, Revoke, and Accept
# ==============================================================================

def test_invitation_creation_locks_organisation_before_duplicate_check(api_environment):
    """Compile the row lock as PostgreSQL FOR UPDATE and check request ordering."""
    client = api_environment["client"]
    admin_headers, _ = auth_headers(api_environment, "admin-a@example.test")
    observed = []

    def capture_orm_select(execute_state):
        if execute_state.is_select:
            observed.append(
                (
                    execute_state.statement,
                    getattr(execute_state.statement, "_for_update_arg", None) is not None,
                )
            )

    event.listen(Session, "do_orm_execute", capture_orm_select)
    try:
        first = client.post(
            "/tenant/members/invitations",
            json={"recipient_email": "serialized@example.test", "role": "contributor"},
            headers=admin_headers,
        )
        assert first.status_code == 201, first.text

        second = client.post(
            "/tenant/members/invitations",
            json={"recipient_email": "serialized@example.test", "role": "contributor"},
            headers=admin_headers,
        )
        assert second.status_code == 409, second.text
    finally:
        event.remove(Session, "do_orm_execute", capture_orm_select)

    rendered = [(str(statement), has_for_update, statement) for statement, has_for_update in observed]
    organisation_lock_positions = [
        index
        for index, (sql, has_for_update, _statement) in enumerate(rendered)
        if has_for_update and "organisations.id" in sql
    ]
    invitation_lookup_positions = [
        index
        for index, (sql, _has_for_update, _statement) in enumerate(rendered)
        if "organisation_invitations.id" in sql and "recipient_email" in sql
    ]
    assert organisation_lock_positions, "Invitation creation did not issue an organisation row lock."
    assert invitation_lookup_positions, "Invitation creation did not check for pending invitations."
    assert organisation_lock_positions[0] < invitation_lookup_positions[0], (
        "The organisation row must be locked before the duplicate-invitation query."
    )

    lock_statement = rendered[organisation_lock_positions[0]][2]
    postgres_sql = str(lock_statement.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in postgres_sql.upper(), postgres_sql


def test_inactive_existing_membership_cannot_receive_a_new_invitation(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")

    existing_email = "admin-a2@example.test"

    with Session(api_environment["engine"]) as db:
        membership = db.scalar(
            select(OrganisationMembership)
            .join(User, User.id == OrganisationMembership.user_id)
            .where(User.email == existing_email)
        )
        assert membership is not None, "Expected existing organisation membership."

        membership.is_active = False
        db.commit()

    response = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": existing_email, "role": "reader"},
        headers=headers,
    )
    assert response.status_code == 409
    assert "inactive organisation membership" in response.json()["detail"].lower()


def test_invitation_lifecycle(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")

    # 1. Invite a new user
    invite_res = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "colleague@example.test", "role": "contributor"},
        headers=headers_a,
    )
    assert invite_res.status_code == 201
    invite_data = invite_res.json()
    assert invite_data["recipient_email"] == "colleague@example.test"
    assert "invitation_token" in invite_data
    token = invite_data["invitation_token"]

    # 2. List pending invitations (does NOT leak token or token hash)
    list_res = client.get("/tenant/members/invitations", headers=headers_a)
    assert list_res.status_code == 200
    pending = list_res.json()["invitations"]
    assert any(p["recipient_email"] == "colleague@example.test" for p in pending)
    assert "invitation_token" not in str(list_res.json())
    assert "token_hash" not in str(list_res.json())

    # 3. Accept invitation
    accept_res = client.post(
        "/auth/invitations/accept",
        json={"token": token, "password": VALID_PASSWORD},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["email"] == "colleague@example.test"

    # 4. Attempt to accept same invitation again fails with 409 Conflict
    reaccept_res = client.post(
        "/auth/invitations/accept",
        json={"token": token, "password": VALID_PASSWORD},
    )
    assert reaccept_res.status_code == 409

    # 5. Log in as new user and verify membership in Tenant Alpha
    new_login = client.post(
        "/auth/login",
        json={"email": "colleague@example.test", "password": VALID_PASSWORD},
    )
    assert new_login.status_code == 200
    assert new_login.json()["role"] == "contributor"


# ==============================================================================
# Tenant Settings: Allowed Domains & Session Timeout
# ==============================================================================

def test_invitation_creation_does_not_expose_tokens_in_production_or_ignore_custom_message(
    api_environment, monkeypatch
):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    organisation_id = api_environment["identities"]["admin-a@example.test"]["organisation"].id

    monkeypatch.setenv("EKIP_ENV", "production")
    production_response = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "new-user@partner.test", "role": "reader"},
        headers=headers,
    )
    assert production_response.status_code == 503

    # Development token exposure is test-only; a custom message cannot be silently dropped
    # while the email delivery provider is unavailable.
    monkeypatch.setenv("EKIP_ENV", "development")
    monkeypatch.setenv("EKIP_EXPOSE_INVITATION_TOKENS", "1")
    message_response = client.post(
        "/tenant/members/invitations",
        json={
            "recipient_email": "new-user@partner.test",
            "role": "reader",
            "message": "Please join our workspace.",
        },
        headers=headers,
    )
    assert message_response.status_code == 503

    with Session(api_environment["engine"]) as db:
        persisted = db.scalar(
            select(OrganisationInvitation.id).where(
                OrganisationInvitation.organisation_id == organisation_id,
                OrganisationInvitation.recipient_email == "new-user@partner.test",
            )
        )
        assert persisted is None


def test_tenant_settings_get_and_update(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")

    # Read default settings
    get_res = client.get("/tenant/settings", headers=headers_a)
    assert get_res.status_code == 200
    assert get_res.json()["session_idle_timeout_minutes"] == 60

    # Update settings
    patch_res = client.patch(
        "/tenant/settings",
        json={"allowed_email_domains": ["partner.test", "example.test"], "session_idle_timeout_minutes": 120},
        headers=headers_a,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["session_idle_timeout_minutes"] == 120
    assert "partner.test" in patch_res.json()["allowed_email_domains"]

    # PATCHing one field must not reset the other field to its request default.
    domains_only = client.patch(
        "/tenant/settings",
        json={"allowed_email_domains": ["new-partner.test"]},
        headers=headers_a,
    )
    assert domains_only.status_code == 200
    assert domains_only.json()["session_idle_timeout_minutes"] == 120
    assert domains_only.json()["allowed_email_domains"] == ["new-partner.test"]

    timeout_only = client.patch(
        "/tenant/settings",
        json={"session_idle_timeout_minutes": 90},
        headers=headers_a,
    )
    assert timeout_only.status_code == 200
    assert timeout_only.json()["session_idle_timeout_minutes"] == 90
    assert timeout_only.json()["allowed_email_domains"] == ["new-partner.test"]

    empty_patch = client.patch("/tenant/settings", json={}, headers=headers_a)
    assert empty_patch.status_code == 422


# ==============================================================================
# Platform Overview & Tenant Suspension
# ==============================================================================

def test_tenant_member_with_platform_role_can_select_independent_platform_scope(api_environment):
    client = api_environment["client"]
    platform_user = api_environment["identities"]["platform-admin@example.test"]["user"]
    with Session(api_environment["engine"]) as db:
        db.add(PlatformRoleAssignment(
            user_id=platform_user.id,
            role=PlatformRole.SUPER_ADMINISTRATOR.value,
            assigned_by_user_id=platform_user.id,
        ))
        db.commit()
    headers, login = auth_headers(
        api_environment, "platform-admin@example.test", auth_scope="platform"
    )
    assert login["organisation_id"] is None
    assert login["permissions"] == []

    profile = client.get("/auth/me", headers=headers)
    assert profile.status_code == 200
    assert profile.json()["organisation"] is None
    assert "organisations:read" in profile.json()["platform_permissions"]
    assert profile.json()["platform_roles"] == [PlatformRole.SUPER_ADMINISTRATOR.value]

    tenant_documents = client.get("/documents", headers=headers)
    assert tenant_documents.status_code == 403


def test_platform_overview_permits_platform_operator(api_environment):
    client = api_environment["client"]
    headers_plat, _ = auth_headers(api_environment, "platform-admin@example.test", auth_scope="platform")
    res = client.get("/platform/overview", headers=headers_plat)
    assert res.status_code == 200
    data = res.json()
    assert data["total_tenants"] >= 2
    assert data["active_tenants"] >= 2


def test_tenant_suspension_locks_out_users_and_reactivation_restores(api_environment):
    client = api_environment["client"]
    headers_plat, _ = auth_headers(api_environment, "platform-admin@example.test", auth_scope="platform")
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")

    org_a_id = api_environment["identities"]["admin-a@example.test"]["organisation"].id
    invite_before_suspend = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "suspension-invite@example.test", "role": "reader"},
        headers=headers_a,
    )
    assert invite_before_suspend.status_code == 201, invite_before_suspend.text

    # 1. Suspend Tenant Alpha. Open invitations are soft-revoked with the tenant.
    suspend_res = client.post(
        f"/platform/organisations/{org_a_id}/suspend",
        json={"reason_code": "security_audit", "note": "Temporary lock"},
        headers=headers_plat,
    )
    assert suspend_res.status_code == 200
    with Session(api_environment["engine"]) as db:
        suspended_invitation = db.get(
            OrganisationInvitation, UUID(invite_before_suspend.json()["id"])
        )
        assert suspended_invitation.revoked_at is not None
        assert suspended_invitation.revoked_by_user_id == api_environment["identities"]["platform-admin@example.test"]["user"].id
        assert suspended_invitation.revocation_reason == "tenant_suspended"

        tenant_membership_id = db.scalar(
            select(OrganisationMembership.id)
            .join(User, User.id == OrganisationMembership.user_id)
            .where(User.email == "admin-a@example.test")
        )
        assert tenant_membership_id is not None, "Expected Tenant Alpha membership."
        tenant_sessions = db.scalars(
            select(RefreshSessionRecord).where(
                RefreshSessionRecord.membership_id == tenant_membership_id
            )
        ).all()
        assert tenant_sessions, "Expected the pre-suspension login to create a refresh session."
        assert all(session.revoked_at is not None for session in tenant_sessions)

    # 2. Existing access token fails on revalidation with 403 Forbidden
    doc_res = client.get("/documents", headers=headers_a)
    assert doc_res.status_code in {401, 403}

    # 3. New login attempt fails
    login_res = client.post(
        "/auth/login",
        json={"email": "admin-a@example.test", "password": VALID_PASSWORD},
    )
    assert login_res.status_code in {401, 403}

    # 4. Reactivate Tenant Alpha
    reactivate_res = client.post(
        f"/platform/organisations/{org_a_id}/reactivate",
        json={"reason_code": "audit_cleared", "note": "Restored"},
        headers=headers_plat,
    )
    assert reactivate_res.status_code == 200
    old_invitation_acceptance = client.post(
        "/auth/invitations/accept",
        json={
            "token": invite_before_suspend.json()["invitation_token"],
            "password": VALID_PASSWORD,
        },
    )
    assert old_invitation_acceptance.status_code == 400

    # 5. Login works again
    relogin_res = client.post(
        "/auth/login",
        json={"email": "admin-a@example.test", "password": VALID_PASSWORD},
    )
    assert relogin_res.status_code == 200


# ==============================================================================
# Platform Role Revocation & Platform Audit
# ==============================================================================

def test_platform_role_listing_and_revocation(api_environment):
    client = api_environment["client"]
    headers_plat, _ = auth_headers(api_environment, "platform-admin@example.test", auth_scope="platform")

    # Search user
    search_res = client.get("/platform/users?q=admin-b", headers=headers_plat)
    assert search_res.status_code == 200
    user_b_id = search_res.json()["users"][0]["id"]

    # Assign role
    assign_res = client.post(
        "/platform/users/roles",
        json={"user_id": user_b_id, "role": "platform_tenant_creator"},
        headers=headers_plat,
    )
    assert assign_res.status_code == 201

    # List platform role holders
    holders_res = client.get("/platform/users/roles", headers=headers_plat)
    assert holders_res.status_code == 200
    assert any(h["email"] == "admin-b@example.test" for h in holders_res.json()["assignments"])

    # Revoke role
    revoke_res = client.delete(
        f"/platform/users/{user_b_id}/roles/platform_tenant_creator",
        headers=headers_plat,
    )
    assert revoke_res.status_code == 200

    headers_b, _ = auth_headers(api_environment, "admin-b@example.test")
    denied = client.get("/platform/overview", headers=headers_b)
    assert denied.status_code == 403


def test_last_active_platform_super_administrator_cannot_be_revoked(api_environment):
    client = api_environment["client"]
    engine = api_environment["engine"]
    actor = api_environment["identities"]["platform-admin@example.test"]["user"]
    target = api_environment["identities"]["admin-b@example.test"]["user"]
    unassigned_legacy_admin = api_environment["identities"]["platform-only@example.test"]["user"]

    # Move the fixture's legacy super-admin to an explicit role assignment so
    # the test exercises the new role-revocation safeguard.
    with Session(engine) as db:
        actor_row = db.get(User, actor.id)
        actor_row.is_platform_admin = False
        # The fixture also includes a separate legacy platform-only user; remove
        # that legacy bootstrap flag so this test has exactly two active super admins.
        db.get(User, unassigned_legacy_admin.id).is_platform_admin = False
        db.add_all([
            PlatformRoleAssignment(user_id=actor.id, role=PlatformRole.SUPER_ADMINISTRATOR.value, assigned_by_user_id=actor.id),
            PlatformRoleAssignment(user_id=target.id, role=PlatformRole.SUPER_ADMINISTRATOR.value, assigned_by_user_id=actor.id),
        ])
        db.commit()

    headers, _ = auth_headers(api_environment, "platform-admin@example.test", auth_scope="platform")

    # Two active super administrators exist, so removing one is permitted.
    first_revoke = client.delete(
        f"/platform/users/{target.id}/roles/platform_super_administrator",
        headers=headers,
    )
    assert first_revoke.status_code == 200, first_revoke.text

    # The actor is now the final active super administrator and must be protected.
    last_revoke = client.delete(
        f"/platform/users/{actor.id}/roles/platform_super_administrator",
        headers=headers,
    )
    assert last_revoke.status_code == 409, last_revoke.text
    assert "last active platform super administrator" in last_revoke.json()["detail"].lower()


def test_platform_audit_events_endpoint(api_environment):
    client = api_environment["client"]
    headers_plat, _ = auth_headers(api_environment, "platform-admin@example.test", auth_scope="platform")

    res = client.get("/platform/audit/events", headers=headers_plat)
    assert res.status_code == 200
    data = res.json()
    assert "events" in data
    assert "count" in data



def test_tenant_idle_timeout_setting_is_enforced_for_existing_access_and_refresh(api_environment):
    client = api_environment["client"]
    organisation_id = api_environment["identities"]["admin-a@example.test"]["organisation"].id
    with Session(api_environment["engine"]) as db:
        db.add(
            OrganisationSettings(
                organisation_id=organisation_id,
                allowed_email_domains=[],
                session_idle_timeout_minutes=5,
            )
        )
        db.commit()

    headers, login = auth_headers(api_environment, "admin-a@example.test")
    with Session(api_environment["engine"]) as db:
        record = db.scalar(
            select(RefreshSessionRecord).where(
                RefreshSessionRecord.token_hash == hashlib.sha256(
                    login["refresh_token"].encode("utf-8")
                ).hexdigest()
            )
        )
        assert record is not None
        # Simulate six minutes of inactivity without waiting in real time.
        record.last_used_at = datetime.now(UTC) - timedelta(minutes=6)
        db.commit()

    protected = client.get("/documents", headers=headers)
    assert protected.status_code == 401
    refreshed = client.post(
        "/auth/refresh",
        json={"refresh_token": login["refresh_token"], "rotation_key": "R" * 43},
    )
    assert refreshed.status_code == 401


def test_platform_audit_sanitizes_tenant_content_and_document_identifiers(api_environment):
    client = api_environment["client"]
    organisation_id = api_environment["identities"]["admin-a@example.test"]["organisation"].id
    actor_id = api_environment["identities"]["admin-a@example.test"]["user"].id
    with Session(api_environment["engine"]) as db:
        db.add(
            AuditEvent(
                actor_user_id=actor_id,
                organisation_id=organisation_id,
                event_type="document.query",
                target_type="query",
                target_id="private-query-record-123",
                details={
                    "action": "query",
                    "outcome": "success",
                    "question": "CONFIDENTIAL TENANT QUESTION",
                    "answer": "CONFIDENTIAL TENANT ANSWER",
                    "document_name": "secret-strategy.pdf",
                },
            )
        )
        db.commit()

    headers, _ = auth_headers(api_environment, "platform-admin@example.test", auth_scope="platform")
    response = client.get("/platform/audit/events", headers=headers)
    assert response.status_code == 200
    body = response.text
    assert "CONFIDENTIAL TENANT QUESTION" not in body
    assert "CONFIDENTIAL TENANT ANSWER" not in body
    assert "secret-strategy.pdf" not in body
    assert "private-query-record-123" not in body
    query_event = next(event for event in response.json()["events"] if event["event_type"] == "document.query")
    assert query_event["target_type"] == "tenant_operation"
    assert query_event["target_id"] is None
    assert query_event["details"] == {"action": "query", "outcome": "success"}


def test_resend_supersedes_old_invitation_and_old_token_is_invalid(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    first = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "resend-target@example.test", "role": "contributor"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/tenant/members/invitations/{first.json()['id']}/resend",
        headers=headers,
    )
    assert second.status_code == 201, second.text

    with Session(api_environment["engine"]) as db:
        old = db.get(OrganisationInvitation, UUID(first.json()["id"]))
        replacement = db.get(OrganisationInvitation, UUID(second.json()["id"]))
        assert old.revoked_at is not None
        assert old.revocation_reason == "superseded"
        assert old.superseded_by_id == replacement.id
        assert old.revoked_by_user_id == api_environment["identities"]["admin-a@example.test"]["user"].id
        assert replacement.revoked_at is None

    rejected = client.post(
        "/auth/invitations/accept",
        json={"token": first.json()["invitation_token"], "password": VALID_PASSWORD},
    )
    assert rejected.status_code == 400
    accepted = client.post(
        "/auth/invitations/accept",
        json={"token": second.json()["invitation_token"], "password": VALID_PASSWORD},
    )
    assert accepted.status_code == 200
    assert accepted.json()["role"] == "contributor"


def test_new_invitation_closes_expired_open_row_before_insert(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    first = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "expired-reinvite@example.test", "role": "reader"},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    first_id = UUID(first.json()["id"])
    with Session(api_environment["engine"]) as db:
        old = db.get(OrganisationInvitation, first_id)
        old.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()

    replacement = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "expired-reinvite@example.test", "role": "contributor"},
        headers=headers,
    )
    assert replacement.status_code == 201, replacement.text
    with Session(api_environment["engine"]) as db:
        old = db.get(OrganisationInvitation, first_id)
        assert old.revoked_at is not None
        assert old.revocation_reason == "expired"
        assert old.revoked_by_user_id is None
        assert old.superseded_by_id is None
        current = db.get(OrganisationInvitation, UUID(replacement.json()["id"]))
        assert current.revoked_at is None


def test_revoke_is_soft_and_revoked_invitation_is_hidden_and_unusable(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    created = client.post(
        "/tenant/members/invitations",
        json={"recipient_email": "revoke-target@example.test", "role": "reader"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    invitation_id = UUID(created.json()["id"])

    revoked = client.delete(f"/tenant/members/invitations/{invitation_id}", headers=headers)
    assert revoked.status_code == 200, revoked.text
    with Session(api_environment["engine"]) as db:
        persisted = db.get(OrganisationInvitation, invitation_id)
        assert persisted is not None
        assert persisted.revoked_at is not None
        assert persisted.revoked_by_user_id == api_environment["identities"]["admin-a@example.test"]["user"].id
        assert persisted.revocation_reason == "revoked_by_admin"
    listed = client.get("/tenant/members/invitations", headers=headers)
    assert invitation_id.hex not in str(listed.json())
    rejected = client.post(
        "/auth/invitations/accept",
        json={"token": created.json()["invitation_token"], "password": VALID_PASSWORD},
    )
    assert rejected.status_code == 400


def test_initial_admin_invitation_activates_only_after_acceptance(api_environment):
    client = api_environment["client"]
    platform_headers, _ = auth_headers(
        api_environment, "platform-admin@example.test", auth_scope="platform"
    )
    actor_id = api_environment["identities"]["platform-admin@example.test"]["user"].id
    organisation = Organisation(
        name="Pending Activation Tenant",
        slug=f"pending-activation-{uuid4().hex[:10]}",
        is_active=False,
    )
    with Session(api_environment["engine"]) as db:
        db.add(organisation)
        db.flush()
        onboarding = TenantOnboarding(
            organisation_id=organisation.id,
            status="pending_admin",
            initial_admin_email="first.admin@example.test",
            idempotency_key=str(uuid4()),
            request_fingerprint="a" * 64,
            created_by_user_id=actor_id,
            approved_by_user_id=actor_id,
            provisioning_attempts=1,
            provisioning_completed_at=datetime.now(UTC),
        )
        db.add(onboarding)
        db.flush()
        # This represents a still-pending 0007-era administrator invitation.
        # Its purpose is unknowable from the old schema, so migration preserves
        # it as "member"; issuance must supersede it for the same recipient.
        legacy_invitation = OrganisationInvitation(
            organisation_id=organisation.id,
            recipient_email="first.admin@example.test",
            role=Role.ORGANISATION_ADMINISTRATOR.value,
            token_hash=uuid4().hex + uuid4().hex,
            invited_by_user_id=actor_id,
            expires_at=datetime.now(UTC) + timedelta(days=3),
        )
        db.add(legacy_invitation)
        db.commit()
        organisation_id = organisation.id
        legacy_invitation_id = legacy_invitation.id

    issued = client.post(
        f"/platform/organisations/{organisation_id}/initial-admin-invitation",
        headers=platform_headers,
    )
    assert issued.status_code == 201, issued.text
    first_invitation_id = UUID(issued.json()["id"])
    with Session(api_environment["engine"]) as db:
        legacy_invitation = db.get(OrganisationInvitation, legacy_invitation_id)
        assert legacy_invitation.purpose == "member"
        assert legacy_invitation.revoked_at is not None
        assert legacy_invitation.revocation_reason == "superseded"
        assert legacy_invitation.superseded_by_id == first_invitation_id
        first_invitation = db.get(OrganisationInvitation, first_invitation_id)
        first_invitation.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    issued_again = client.post(
        f"/platform/organisations/{organisation_id}/initial-admin-invitation",
        headers=platform_headers,
    )
    assert issued_again.status_code == 201, issued_again.text
    invitation_token = issued_again.json()["invitation_token"]
    with Session(api_environment["engine"]) as db:
        expired_invitation = db.get(OrganisationInvitation, first_invitation_id)
        assert expired_invitation.revocation_reason == "expired"
        assert expired_invitation.revoked_at is not None
        onboarding_row = db.scalar(
            select(TenantOnboarding).where(TenantOnboarding.organisation_id == organisation_id)
        )
        assert onboarding_row.initial_admin_invitation_id == UUID(issued_again.json()["id"])
    old_token = client.post(
        "/auth/invitations/accept",
        json={"token": issued.json()["invitation_token"], "password": VALID_PASSWORD},
    )
    assert old_token.status_code == 400
    before_accept = client.get("/platform/organisations", headers=platform_headers)
    entry = next(item for item in before_accept.json()["organisations"] if item["id"] == str(organisation_id))
    assert entry["status"] == "pending_admin"
    assert entry["is_active"] is False

    accepted = client.post(
        "/auth/invitations/accept",
        json={"token": invitation_token, "password": VALID_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tenant_activated"] is True
    with Session(api_environment["engine"]) as db:
        organisation_row = db.get(Organisation, organisation_id)
        onboarding_row = db.scalar(
            select(TenantOnboarding).where(TenantOnboarding.organisation_id == organisation_id)
        )
        invitation_row = db.get(OrganisationInvitation, UUID(issued_again.json()["id"]))
        assert organisation_row.is_active is True
        assert onboarding_row.status == "active"
        assert onboarding_row.initial_admin_invitation_accepted_at is not None
        assert invitation_row.accepted_at is not None
        assert invitation_row.accepted_by_user_id is not None
        member = db.scalar(
            select(OrganisationMembership).where(
                OrganisationMembership.organisation_id == organisation_id,
                OrganisationMembership.user_id == invitation_row.accepted_by_user_id,
            )
        )
        assert member.role == Role.ORGANISATION_ADMINISTRATOR
        assert member.is_active is True


def test_tenant_scoped_platform_operator_cannot_call_platform_api(api_environment):
    client = api_environment["client"]
    tenant_scope_headers, _ = auth_headers(
        api_environment, "platform-admin@example.test", auth_scope="tenant"
    )
    response = client.get("/platform/overview", headers=tenant_scope_headers)
    assert response.status_code == 403
    assert "platform-scoped" in response.json()["detail"].lower()
