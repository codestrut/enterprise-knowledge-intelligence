"""PostgreSQL-only regression for duplicate invitation creation races.

Run against a disposable loopback database whose name contains 'test' by
setting EKIP_TEST_DATABASE_URL. The test never cleans or drops database rows;
use a disposable test database and drop it after the run.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import importlib
import os
import secrets
import sys
import types
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from src.auth.models import (
    Organisation,
    OrganisationInvitation,
    OrganisationMembership,
    User,
)
from src.auth.passwords import hash_password
from src.auth.permissions import Role


_RAW_URL = os.environ.get("EKIP_TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("EKIP_TEST_DATABASE_URL is not configured", allow_module_level=True)

_URL = make_url(_RAW_URL)
if _URL.drivername != "postgresql+psycopg":
    pytest.skip("EKIP_TEST_DATABASE_URL must use postgresql+psycopg", allow_module_level=True)
if _URL.host not in {"127.0.0.1", "localhost", "::1"}:
    pytest.skip("PostgreSQL integration tests require a loopback host", allow_module_level=True)
if not _URL.database or "test" not in _URL.database.lower():
    pytest.skip("PostgreSQL database name must contain 'test'", allow_module_level=True)


class _InvitationTestKnowledgeBase:
    def __init__(self, embedder=None, reranker=None):
        self.embedder = embedder or object()
        self.reranker = reranker
        self.documents = {}
        self.chunks = []


class _InvitationTestPipeline:
    def __init__(self, knowledge_base=None, **_kwargs):
        self.knowledge_base = knowledge_base
        self.tenant_id = getattr(knowledge_base, "tenant_id", None)


@pytest.fixture
def postgres_invitation_api(monkeypatch, tmp_path):
    """Create a real PostgreSQL-backed API fixture with synthetic identities."""
    engine = create_engine(_URL, pool_pre_ping=True, pool_size=6, max_overflow=4)
    previous_api_module = None
    try:
        with engine.connect() as connection:
            database_name = connection.scalar(text("SELECT current_database()"))
            if database_name != _URL.database:
                pytest.fail("Connected PostgreSQL database does not match configured test name")
            existing_tables = set(inspect(connection).get_table_names())
            if "alembic_version" not in existing_tables and existing_tables:
                pytest.fail("Refusing to migrate a non-empty unversioned test database")
            if "alembic_version" in existing_tables:
                current = connection.scalar(text("SELECT version_num FROM alembic_version"))
                if current not in {
                    "0001_identity_foundation",
                    "0002_auth_refresh_sessions",
                    "0003_auth_hardening",
                    "0004_scoped_security_audit",
                    "0005_tenant_onboarding",
                    "0006_platform_roles_and_recovery",
                    "0007_tenant_admin",
                    "0008_invitation_lifecycle",
                }:
                    pytest.fail("Refusing to change an unknown Alembic revision")

        previous_auth_url = os.environ.get("EKIP_DATABASE_URL")
        os.environ["EKIP_DATABASE_URL"] = _RAW_URL
        try:
            command.upgrade(Config("alembic.ini"), "head")
        finally:
            if previous_auth_url is None:
                os.environ.pop("EKIP_DATABASE_URL", None)
            else:
                os.environ["EKIP_DATABASE_URL"] = previous_auth_url

        monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", "invitation-race-test-secret-" + secrets.token_hex(32))
        monkeypatch.setenv("EKIP_ENV", "development")
        monkeypatch.setenv("EKIP_EXPOSE_INVITATION_TOKENS", "1")

        grounding_module = types.ModuleType("src.generation.grounding_evaluator")
        grounding_module.GroundingEvaluator = type(
            "GroundingEvaluator", (), {"__init__": lambda self, *args, **kwargs: None}
        )
        knowledge_base_module = types.ModuleType("src.knowledge_base")
        knowledge_base_module.KnowledgeBase = _InvitationTestKnowledgeBase
        rag_pipeline_module = types.ModuleType("src.rag_pipeline")
        rag_pipeline_module.RAGPipeline = _InvitationTestPipeline
        monkeypatch.setitem(sys.modules, "src.generation.grounding_evaluator", grounding_module)
        monkeypatch.setitem(sys.modules, "src.knowledge_base", knowledge_base_module)
        monkeypatch.setitem(sys.modules, "src.rag_pipeline", rag_pipeline_module)
        previous_api_module = sys.modules.pop("src.api.main", None)
        api = importlib.import_module("src.api.main")

        from src.api.tenant_storage import TenantWorkspaceRegistry
        from src.auth.dependencies import get_auth_db

        monkeypatch.setattr(
            api,
            "tenant_workspaces",
            TenantWorkspaceRegistry(
                tmp_path / "tenant-workspaces",
                shared_embedder=object(),
                shared_reranker=object(),
                pipeline_dependencies={},
                knowledge_base_factory=_InvitationTestKnowledgeBase,
                pipeline_factory=_InvitationTestPipeline,
            ),
        )

        with Session(engine) as db:
            organisation = Organisation(
                name=f"Invitation concurrency {uuid4().hex}",
                slug=f"invitation-concurrency-{uuid4().hex}",
                is_active=True,
            )
            admin = User(
                email=f"invitation-admin-{uuid4().hex}@example.invalid",
                password_hash=hash_password("violet-cactus-orbit-sailed"),
            )
            membership = OrganisationMembership(
                user=admin,
                organisation=organisation,
                role=Role.ORGANISATION_ADMINISTRATOR,
                is_active=True,
            )
            db.add_all([organisation, admin, membership])
            db.commit()
            db.refresh(organisation)
            admin_email = admin.email
            organisation_id = organisation.id

        def override_auth_db():
            with Session(engine) as db:
                yield db

        monkeypatch.setitem(api.app.dependency_overrides, get_auth_db, override_auth_db)
        with TestClient(api.app) as client:
            login = client.post(
                "/auth/login",
                json={"email": admin_email, "password": "violet-cactus-orbit-sailed"},
            )
            assert login.status_code == 200, login.text
            yield {
                "client": client,
                "engine": engine,
                "organisation_id": organisation_id,
                "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
            }
    finally:
        engine.dispose()
        sys.modules.pop("src.api.main", None)
        if previous_api_module is not None:
            sys.modules["src.api.main"] = previous_api_module


def test_postgres_concurrent_invitation_creation_creates_only_one_pending_invite(
    postgres_invitation_api,
):
    """Two simultaneous requests for one tenant/email produce one invite only."""
    client = postgres_invitation_api["client"]
    headers = postgres_invitation_api["headers"]
    organisation_id = postgres_invitation_api["organisation_id"]
    recipient = f"concurrent-invite-{uuid4().hex}@example.invalid"
    barrier = Barrier(2)

    def create_invitation():
        barrier.wait(timeout=10)
        return client.post(
            "/tenant/members/invitations",
            json={"recipient_email": recipient, "role": "contributor"},
            headers=headers,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create_invitation) for _ in range(2)]
        responses = [future.result(timeout=30) for future in futures]

    statuses = [response.status_code for response in responses]
    assert statuses.count(201) == 1, [response.text for response in responses]
    assert statuses.count(409) == 1, [response.text for response in responses]

    with Session(postgres_invitation_api["engine"]) as db:
        pending = db.scalars(
            select(OrganisationInvitation).where(
                OrganisationInvitation.organisation_id == organisation_id,
                OrganisationInvitation.recipient_email == recipient,
                OrganisationInvitation.accepted_at.is_(None),
                OrganisationInvitation.revoked_at.is_(None),
            )
        ).all()
    assert len(pending) == 1
