"""Model-free API security and tenant-isolation acceptance tests."""

import importlib
import json
import logging
import sys
import threading
import types
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.auth.dependencies import get_auth_db
from src.auth.models import AuditEvent, Base, Organisation, OrganisationMembership, RefreshSessionRecord, User
from src.auth.passwords import hash_password
from src.auth.permissions import Permission, Role, permissions_for_role


VALID_PASSWORD = "violet-cactus-orbit-sailed"


class FakeKnowledgeBase:
    def __init__(self, embedder=None, reranker=None):
        self.embedder = embedder or object()
        self.reranker = reranker
        self.tenant_id = None
        self.documents = {}
        self.chunks = []

    def add_pdf(self, file_path, document_id=None):
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(path.name)
        document_id = document_id or str(uuid4())
        record = {
            "document_id": document_id,
            "filename": path.name,
            "source": str(path),
            "page_count": 1,
            "chunk_count": 1,
            "status": "indexed",
        }
        self.documents[document_id] = record.copy()
        self.chunks.append({"metadata": {"document_id": document_id, "filename": path.name}})
        return record.copy()

    def list_documents(self):
        return [record.copy() for record in self.documents.values()]

    def delete_document(self, document_id):
        if document_id not in self.documents:
            raise KeyError(document_id)
        record = self.documents.pop(document_id)
        self.chunks = [chunk for chunk in self.chunks if chunk["metadata"]["document_id"] != document_id]
        return record.copy()


class FakePipeline:
    def __init__(self, knowledge_base=None):
        self.knowledge_base = knowledge_base
        self.tenant_id = getattr(knowledge_base, "tenant_id", None)

    def query(self, question, top_k=5, tenant_id=None):
        if str(tenant_id) != str(self.tenant_id):
            raise ValueError("Tenant context does not match the knowledge base.")
        records = self.knowledge_base.list_documents()
        sources = [
            {"text": record["filename"], "metadata": {"document_id": record["document_id"]}}
            for record in records
        ]
        return {
            "question": question,
            "answer": "Test answer.",
            "sources": sources,
            "invalid_citations": [],
            "refused": not bool(sources),
            "top_k": top_k,
        }


@pytest.fixture
def api_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", "test-api-signing-secret-over-32-characters")
    monkeypatch.delenv("EKIP_ENABLE_API_DOCS", raising=False)
    knowledge_base_module = types.ModuleType("src.knowledge_base")
    knowledge_base_module.KnowledgeBase = FakeKnowledgeBase
    rag_pipeline_module = types.ModuleType("src.rag_pipeline")
    rag_pipeline_module.RAGPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "src.knowledge_base", knowledge_base_module)
    monkeypatch.setitem(sys.modules, "src.rag_pipeline", rag_pipeline_module)
    sys.modules.pop("src.api.main", None)
    api = importlib.import_module("src.api.main")

    api.tenant_workspaces = api.TenantWorkspaceRegistry(
        tmp_path / "tenants",
        shared_embedder=object(),
        shared_reranker=object(),
        pipeline_dependencies={},
        knowledge_base_factory=FakeKnowledgeBase,
        pipeline_factory=FakePipeline,
    )
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'auth.sqlite'}",
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
        org_a = Organisation(name="Tenant A", slug="tenant-a")
        org_b = Organisation(name="Tenant B", slug="tenant-b")
        db.add_all([org_a, org_b])
        db.flush()
        specs = [
            ("admin-a@example.test", Role.ORGANISATION_ADMINISTRATOR, org_a, False),
            ("admin-b@example.test", Role.ORGANISATION_ADMINISTRATOR, org_b, False),
            ("reader-a@example.test", Role.READER, org_a, False),
            ("contributor-a@example.test", Role.CONTRIBUTOR, org_a, False),
            ("platform-reader@example.test", Role.READER, org_a, True),
        ]
        for email, role, organisation, platform in specs:
            user = User(
                email=email,
                password_hash=hash_password(VALID_PASSWORD),
                is_platform_admin=platform,
            )
            membership = OrganisationMembership(user=user, organisation=organisation, role=role)
            db.add_all([user, membership])
            identities[email] = {"user": user, "organisation": organisation, "membership": membership, "role": role}
        no_membership = User(
            email="platform-only@example.test",
            password_hash=hash_password(VALID_PASSWORD),
            is_platform_admin=True,
        )
        db.add(no_membership)
        identities[no_membership.email] = {"user": no_membership, "organisation": None, "role": None}
        db.commit()
        for identity in identities.values():
            db.refresh(identity["user"])
            if identity["organisation"] is not None:
                db.refresh(identity["organisation"])
            if "membership" in identity:
                db.refresh(identity["membership"])

    def override_db():
        with Session(engine) as db:
            yield db

    api.app.dependency_overrides[get_auth_db] = override_db
    with TestClient(api.app) as client:
        yield {"api": api, "client": client, "engine": engine, "identities": identities, "root": tmp_path / "tenants"}
    api.app.dependency_overrides.clear()
    engine.dispose()
    sys.modules.pop("src.api.main", None)


def login(environment, email, *, organisation_id=None):
    body = {"email": email, "password": VALID_PASSWORD}
    if organisation_id is not None:
        body["organisation_id"] = str(organisation_id)
    response = environment["client"].post("/auth/login", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def auth_headers(environment, email, *, organisation_id=None):
    result = login(environment, email, organisation_id=organisation_id)
    assert "access_token" in result
    return {"Authorization": f"Bearer {result['access_token']}"}, result


def test_health_is_minimal_public_and_sensitive_routes_require_auth(api_environment):
    client = api_environment["client"]
    assert client.get("/health").json() == {"status": "ok"}
    document_id = str(uuid4())
    responses = [
        client.get("/documents"),
        client.get("/tenant/status"),
        client.get("/auth/me"),
        client.get("/audit/events"),
        client.post("/documents", files={"file": ("a.pdf", b"%PDF-test", "application/pdf")}),
        client.post("/query", json={"question": "hello"}),
        client.get(f"/documents/{document_id}/file"),
        client.delete(f"/documents/{document_id}"),
    ]
    assert [response.status_code for response in responses] == [401] * len(responses)
    assert all(response.headers.get("www-authenticate") == "Bearer" for response in responses)


def test_login_refresh_and_logout_issue_short_lived_revalidatable_bearer(api_environment):
    client = api_environment["client"]
    result = login(api_environment, "admin-a@example.test")
    assert result["token_type"] == "bearer"
    assert result["expires_in"] == 600
    assert result["role"] == Role.ORGANISATION_ADMINISTRATOR.value
    assert Permission.DOCUMENTS_UPLOAD.value in result["permissions"]

    rotation_key = "R" * 43
    refreshed = client.post(
        "/auth/refresh",
        json={"refresh_token": result["refresh_token"], "rotation_key": rotation_key},
    )
    assert refreshed.status_code == 200, refreshed.text
    token = refreshed.json()["access_token"]
    logged_out = client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logged_out.status_code == 204
    from src.auth.access_tokens import decode_access_token
    claims = decode_access_token(token)
    with Session(api_environment["engine"]) as db:
        sessions = db.scalars(select(RefreshSessionRecord).where(RefreshSessionRecord.family_id == claims.family_id)).all()
        assert sessions and all(session.revoked_at is not None for session in sessions)
    assert client.get("/documents", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_current_user_profile_is_derived_from_authenticated_membership(api_environment):
    client = api_environment["client"]
    headers, _result = auth_headers(api_environment, "admin-a@example.test")
    response = client.get("/auth/me", headers=headers, params={"user_id": "forged", "organisation_id": "other"})
    assert response.status_code == 200, response.text
    profile = response.json()
    assert profile == {
        "email": "admin-a@example.test",
        "organisation": {
            "id": str(api_environment["identities"]["admin-a@example.test"]["organisation"].id),
            "name": "Tenant A",
        },
        "role": Role.ORGANISATION_ADMINISTRATOR.value,
        "permissions": sorted(permission.value for permission in permissions_for_role(Role.ORGANISATION_ADMINISTRATOR)),
    }
    assert set(profile) == {"email", "organisation", "role", "permissions"}
    assert "password_hash" not in profile and "access_token" not in profile and "refresh_token" not in profile


def test_current_user_profile_rejects_inactive_membership(api_environment):
    headers, _result = auth_headers(api_environment, "reader-a@example.test")
    membership_id = api_environment["identities"]["reader-a@example.test"]["membership"].id
    with Session(api_environment["engine"]) as db:
        membership = db.get(OrganisationMembership, membership_id)
        membership.is_active = False
        db.commit()
    response = api_environment["client"].get("/auth/me", headers=headers)
    assert response.status_code == 401


def test_bad_credentials_and_tampered_access_token_are_401(api_environment):
    client = api_environment["client"]
    bad = client.post("/auth/login", json={"email": "admin-a@example.test", "password": "incorrect"})
    assert bad.status_code == 401
    with Session(api_environment["engine"]) as db:
        failed_event = db.scalar(select(AuditEvent).where(AuditEvent.event_type == "auth.login_failed"))
        assert failed_event is not None
        assert failed_event.actor_user_id == api_environment["identities"]["admin-a@example.test"]["user"].id
        assert failed_event.organisation_id == api_environment["identities"]["admin-a@example.test"]["organisation"].id
        assert failed_event.details == {"action": "login", "outcome": "failure", "reason": "invalid_credentials"}
        assert "incorrect" not in str(failed_event.details)
    headers, _result = auth_headers(api_environment, "admin-a@example.test")
    body, signature = headers["Authorization"].split(" ", 1)[1].split(".")
    headers["Authorization"] = f"Bearer {body}.{signature[:-1]}A"
    assert client.get("/documents", headers=headers).status_code == 401


def test_readers_cannot_upload_or_delete_and_platform_admin_has_no_extra_tenant_access(api_environment):
    client = api_environment["client"]
    reader, _ = auth_headers(api_environment, "reader-a@example.test")
    upload = client.post("/documents", files={"file": ("r.pdf", b"%PDF-test", "application/pdf")}, headers=reader)
    assert upload.status_code == 403
    assert client.delete(f"/documents/{uuid4()}", headers=reader).status_code == 403
    assert client.get("/documents", headers=reader).status_code == 200

    platform_reader, _ = auth_headers(api_environment, "platform-reader@example.test")
    assert client.post("/documents", files={"file": ("p.pdf", b"%PDF-test", "application/pdf")}, headers=platform_reader).status_code == 403
    assert client.get("/documents", headers=platform_reader).status_code == 200
    no_tenant = client.post("/auth/login", json={"email": "platform-only@example.test", "password": VALID_PASSWORD})
    assert no_tenant.status_code == 401


def test_membership_permission_bundle_denies_tenant_administration_to_contributors(api_environment):
    headers, _result = auth_headers(api_environment, "contributor-a@example.test")
    token = headers["Authorization"].split(" ", 1)[1]
    from src.auth.access_tokens import decode_access_token
    from src.auth.dependencies import AuthenticatedContext
    from src.auth.service import AuthenticatedPrincipal
    from src.auth.permissions import permissions_for_role

    claims = decode_access_token(token)
    principal = AuthenticatedPrincipal(
        claims.user_id,
        claims.membership_id,
        claims.organisation_id,
        Role.CONTRIBUTOR,
        permissions_for_role(Role.CONTRIBUTOR),
    )
    admin_check = api_environment["api"].require_permission(Permission.MEMBERS_MANAGE)
    with pytest.raises(HTTPException) as denied:
        admin_check(AuthenticatedContext(principal, claims.family_id))
    assert denied.value.status_code == 403


def _upload(client, headers, filename, content=None):
    return client.post(
        "/documents",
        files={"file": (filename, content or b"%PDF-1.4\nsynthetic PDF", "application/pdf")},
        headers=headers,
    )


def test_documents_queries_downloads_and_deletion_are_isolated_by_membership(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")
    headers_b, _ = auth_headers(api_environment, "admin-b@example.test")
    upload_a = _upload(client, headers_a, "tenant-a.pdf")
    upload_b = _upload(client, headers_b, "tenant-b.pdf")
    assert upload_a.status_code == upload_b.status_code == 201
    id_a = upload_a.json()["document"]["document_id"]
    id_b = upload_b.json()["document"]["document_id"]

    assert [row["filename"] for row in client.get("/documents", headers=headers_a).json()["documents"]] == ["tenant-a.pdf"]
    assert [row["filename"] for row in client.get("/documents", headers=headers_b).json()["documents"]] == ["tenant-b.pdf"]
    query_a = client.post("/query", json={"question": "tenant-b.pdf"}, headers=headers_a)
    assert query_a.status_code == 200
    assert all(
        "tenant-b.pdf" not in str(source.get("text", ""))
        and "tenant-b.pdf" not in str(source.get("metadata", {}))
        for source in query_a.json()["sources"]
    )
    assert client.get(f"/documents/{id_a}/file", headers=headers_a).status_code == 200
    assert client.get(f"/documents/{id_b}/file", headers=headers_a).status_code == 404
    assert client.delete(f"/documents/{id_b}", headers=headers_a).status_code == 404
    assert client.get("/documents", headers=headers_b).json()["documents"][0]["document_id"] == id_b
    assert client.delete(f"/documents/{id_a}", headers=headers_a).status_code == 200
    assert client.get("/documents", headers=headers_a).json() == {"count": 0, "documents": []}
    assert client.delete(f"/documents/{id_a}", headers=headers_a).status_code == 404


def test_duplicate_pdf_is_rejected_only_inside_the_authenticated_tenant(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")
    headers_b, _ = auth_headers(api_environment, "admin-b@example.test")
    content = b"%PDF-1.4\nshared synthetic test fixture"
    first = _upload(client, headers_a, "same.pdf", content)
    assert first.status_code == 201
    duplicate = _upload(client, headers_a, "renamed.pdf", content)
    assert duplicate.status_code == 409
    other_tenant = _upload(client, headers_b, "same.pdf", content)
    assert other_tenant.status_code == 201


def test_tampered_organisation_fields_and_path_traversal_cannot_select_other_storage(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")
    forged = client.post(
        "/query",
        json={"question": "anything", "organisation_id": str(uuid4())},
        headers=headers_a,
    )
    assert forged.status_code == 422
    outside = api_environment["root"].parent / "outside.pdf"
    outside.write_bytes(b"protected")
    attempted = client.delete("/documents/..%2F..%2Foutside", headers=headers_a)
    assert attempted.status_code in {404, 405}
    assert outside.read_bytes() == b"protected"


def test_restoration_after_registry_rebuild_keeps_tenant_documents_separate(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")
    headers_b, _ = auth_headers(api_environment, "admin-b@example.test")
    doc_a = _upload(client, headers_a, "persist-a.pdf").json()["document"]["document_id"]
    doc_b = _upload(client, headers_b, "persist-b.pdf").json()["document"]["document_id"]
    api = api_environment["api"]
    api.tenant_workspaces = api.TenantWorkspaceRegistry(
        api_environment["root"],
        shared_embedder=object(),
        shared_reranker=object(),
        pipeline_dependencies={},
        knowledge_base_factory=FakeKnowledgeBase,
        pipeline_factory=FakePipeline,
    )
    api.tenant_workspaces.restore_all()
    assert [d["document_id"] for d in client.get("/documents", headers=headers_a).json()["documents"]] == [doc_a]
    assert [d["document_id"] for d in client.get("/documents", headers=headers_b).json()["documents"]] == [doc_b]
    # Restore must keep the original filenames in the live record, chunks and citations.
    assert [d["filename"] for d in client.get("/documents", headers=headers_a).json()["documents"]] == ["persist-a.pdf"]
    assert [d["filename"] for d in client.get("/documents", headers=headers_b).json()["documents"]] == ["persist-b.pdf"]
    sources = client.post("/query", json={"question": "persist"}, headers=headers_a).json()["sources"]
    assert [source["text"] for source in sources] == ["persist-a.pdf"]
    organisation_a = api_environment["identities"]["admin-a@example.test"]["organisation"].id
    restored_chunks = api.tenant_workspaces.workspace_for(organisation_a).knowledge_base.chunks
    assert [chunk["metadata"]["filename"] for chunk in restored_chunks] == ["persist-a.pdf"]
    download = client.get(f"/documents/{doc_a}/file", headers=headers_a)
    assert "persist-a.pdf" in download.headers["content-disposition"]


def test_validation_and_response_records_do_not_expose_paths(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    assert client.post("/documents", files={"file": ("x.txt", b"not pdf", "text/plain")}, headers=headers).status_code == 400
    assert client.post("/documents", files={"file": ("x.pdf", b"not pdf", "application/pdf")}, headers=headers).status_code == 400
    uploaded = _upload(client, headers, "safe.pdf")
    assert uploaded.status_code == 201
    assert "source" not in uploaded.json()["document"]
    assert str(api_environment["root"]) not in uploaded.text


def test_query_validation_and_tenant_specific_status(api_environment):
    client = api_environment["client"]
    headers, result = auth_headers(api_environment, "reader-a@example.test")
    assert client.get("/tenant/status", headers=headers).json() == {
        "organisation_id": result["organisation_id"],
        "document_count": 0,
        "chunk_count": 0,
        "failed_document_count": 0,
    }
    assert client.post("/query", json={"question": "", "top_k": 5}, headers=headers).status_code == 422
    assert client.post("/query", json={"question": "hello", "top_k": 100}, headers=headers).status_code == 422


def test_audit_events_cover_document_actions_and_are_tenant_scoped(api_environment):
    client = api_environment["client"]
    headers_a, _ = auth_headers(api_environment, "admin-a@example.test")
    headers_b, _ = auth_headers(api_environment, "admin-b@example.test")
    uploaded_a = _upload(client, headers_a, "audit-a.pdf")
    uploaded_b = _upload(client, headers_b, "audit-b.pdf")
    assert uploaded_a.status_code == uploaded_b.status_code == 201
    document_a = uploaded_a.json()["document"]["document_id"]
    assert client.post("/query", json={"question": "private question text"}, headers=headers_a).status_code == 200
    assert client.delete(f"/documents/{document_a}", headers=headers_a).status_code == 200

    audit_a = client.get("/audit/events", headers=headers_a)
    audit_b = client.get("/audit/events", headers=headers_b)
    assert audit_a.status_code == audit_b.status_code == 200
    org_a = api_environment["identities"]["admin-a@example.test"]["organisation"].id
    org_b = api_environment["identities"]["admin-b@example.test"]["organisation"].id
    events_a = audit_a.json()["events"]
    events_b = audit_b.json()["events"]
    assert events_a and events_b
    assert all(event["organisation_id"] == str(org_a) for event in events_a)
    assert all(event["organisation_id"] == str(org_b) for event in events_b)
    assert {event["event_type"] for event in events_a} >= {"document.upload", "knowledge.query", "document.delete"}
    for event in events_a:
        assert event["actor_user_id"] == str(api_environment["identities"]["admin-a@example.test"]["user"].id)
        assert event["details"]["outcome"] == "success"
        assert "private question text" not in str(event)
        assert "access_token" not in str(event) and "refresh_token" not in str(event)
    assert all("audit-b.pdf" not in str(event) for event in events_a)


def test_only_organisation_administrators_can_read_scoped_audit_events(api_environment):
    reader, _ = auth_headers(api_environment, "reader-a@example.test")
    contributor, _ = auth_headers(api_environment, "contributor-a@example.test")
    platform_reader, _ = auth_headers(api_environment, "platform-reader@example.test")
    assert api_environment["client"].get("/audit/events", headers=reader).status_code == 403
    assert api_environment["client"].get("/audit/events", headers=contributor).status_code == 403
    assert api_environment["client"].get("/audit/events", headers=platform_reader).status_code == 403
    assert api_environment["client"].get("/audit/events?limit=101", headers=auth_headers(api_environment, "admin-a@example.test")[0]).status_code == 422


def test_audit_unavailable_blocks_upload_query_and_delete(api_environment, monkeypatch):
    api = api_environment["api"]
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    existing = _upload(client, headers, "preserved.pdf")
    assert existing.status_code == 201
    document_id = existing.json()["document"]["document_id"]

    def fail_audit(*_args, **_kwargs):
        raise api._audit_unavailable()

    monkeypatch.setattr(api, "_start_audit_event", fail_audit)
    assert _upload(client, headers, "blocked.pdf").status_code == 503
    assert client.post("/query", json={"question": "do not run"}, headers=headers).status_code == 503
    assert client.delete(f"/documents/{document_id}", headers=headers).status_code == 503
    assert [row["filename"] for row in client.get("/documents", headers=headers).json()["documents"]] == ["preserved.pdf"]


def test_audit_completion_failure_rolls_back_uploaded_document(api_environment, monkeypatch):
    api = api_environment["api"]
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")

    def fail_completion(*_args, **_kwargs):
        raise api._audit_unavailable()

    monkeypatch.setattr(api, "_finish_audit_event", fail_completion)
    response = _upload(client, headers, "audit-rollback.pdf")
    assert response.status_code == 503
    assert client.get("/documents", headers=headers).json() == {"count": 0, "documents": []}
    audit = client.get("/audit/events", headers=headers).json()["events"]
    pending = next(event for event in audit if event["event_type"] == "document.upload")
    assert pending["details"]["outcome"] == "started"


# --- Run A (Task 05 audit fixes) regression tests -------------------------------------------


def _reload_api_module(monkeypatch):
    knowledge_base_module = types.ModuleType("src.knowledge_base")
    knowledge_base_module.KnowledgeBase = FakeKnowledgeBase
    rag_pipeline_module = types.ModuleType("src.rag_pipeline")
    rag_pipeline_module.RAGPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "src.knowledge_base", knowledge_base_module)
    monkeypatch.setitem(sys.modules, "src.rag_pipeline", rag_pipeline_module)
    sys.modules.pop("src.api.main", None)
    return importlib.import_module("src.api.main")


def test_query_internal_failures_return_fixed_5xx_with_request_id(api_environment, monkeypatch):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")

    def misconfigured(self, question, top_k=5, tenant_id=None):
        raise ValueError("OPENAI_API_KEY is not set. Add it to the project's .env file.")

    monkeypatch.setattr(FakePipeline, "query", misconfigured)
    response = client.post("/query", json={"question": "configuration canary"}, headers=headers)
    assert 500 <= response.status_code < 600
    body = response.json()
    assert body["detail"] == "Knowledge query failed."
    assert "OPENAI" not in response.text and ".env" not in response.text
    assert body["request_id"] and response.headers["x-request-id"] == body["request_id"]


def test_upload_internal_and_validation_errors_use_fixed_text(api_environment, monkeypatch):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")

    def missing(self, file_path, document_id=None):
        raise FileNotFoundError("PDF file not found: /srv/private/secret-location.pdf")

    monkeypatch.setattr(FakeKnowledgeBase, "add_pdf", missing)
    response = _upload(client, headers, "missing.pdf")
    assert response.status_code == 500
    assert response.json()["detail"] == "Document upload or indexing failed."
    assert "secret-location" not in response.text and "/srv/private" not in response.text
    assert response.json()["request_id"] == response.headers["x-request-id"]

    def unreadable(self, file_path, document_id=None):
        raise ValueError("No pages could be extracted from: internal-name-canary.pdf")

    monkeypatch.setattr(FakeKnowledgeBase, "add_pdf", unreadable)
    response = _upload(client, headers, "unreadable.pdf")
    assert response.status_code == 400
    assert response.json()["detail"] == "The PDF could not be processed. Upload a text-based PDF."
    assert "internal-name-canary" not in response.text


@pytest.mark.parametrize("secret", [None, "too-short-signing-secret"])
def test_startup_refuses_missing_or_short_signing_key_before_any_session(monkeypatch, tmp_path, secret):
    if secret is None:
        monkeypatch.delenv("EKIP_ACCESS_TOKEN_SECRET", raising=False)
    else:
        monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", secret)
    api = _reload_api_module(monkeypatch)
    try:
        api.tenant_workspaces = api.TenantWorkspaceRegistry(
            tmp_path / "tenants",
            shared_embedder=object(),
            shared_reranker=object(),
            pipeline_dependencies={},
            knowledge_base_factory=FakeKnowledgeBase,
            pipeline_factory=FakePipeline,
        )
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'auth.sqlite'}")
        Base.metadata.create_all(engine)

        def override_db():
            with Session(engine) as db:
                yield db

        api.app.dependency_overrides[get_auth_db] = override_db
        with pytest.raises(RuntimeError, match="EKIP_ACCESS_TOKEN_SECRET") as refused:
            with TestClient(api.app):
                pass
        if secret is not None:
            assert secret not in str(refused.value)
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(RefreshSessionRecord)) == 0
        assert not (tmp_path / "tenants").exists()
        engine.dispose()
    finally:
        api.app.dependency_overrides.clear()
        sys.modules.pop("src.api.main", None)


def test_oversized_inputs_are_rejected_without_echoing_or_logging_values(api_environment, caplog):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    caplog.set_level(logging.DEBUG)
    question_canary = "QCANARY-" + "q" * 4000
    assert client.post("/query", json={"question": question_canary}, headers=headers).status_code == 422
    assert client.post("/query", json={"question": "q" * 4000}, headers=headers).status_code == 200
    password_canary = "PCANARY-" + "p" * 128
    oversized = client.post("/auth/login", json={"email": "admin-a@example.test", "password": password_canary})
    assert oversized.status_code == 422
    assert "PCANARY" not in oversized.text
    longest_allowed = "p" * 128
    assert client.post("/auth/login", json={"email": "admin-a@example.test", "password": longest_allowed}).status_code == 401
    long_name = "f" * 252 + ".pdf"
    rejected = _upload(client, headers, long_name)
    assert rejected.status_code == 422
    assert long_name not in rejected.text
    assert _upload(client, headers, "f" * 251 + ".pdf").status_code == 201
    assert "QCANARY" not in caplog.text and "PCANARY" not in caplog.text and long_name not in caplog.text


def test_protected_routes_return_503_when_auth_database_is_unavailable(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")

    class UnavailableSession:
        def _fail(self, *_args, **_kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused by db-host-canary"))

        execute = scalar = scalars = _fail

        def in_transaction(self):
            return False

        def rollback(self):
            return None

        def close(self):
            return None

    def unavailable_db():
        yield UnavailableSession()

    api_environment["api"].app.dependency_overrides[get_auth_db] = unavailable_db
    responses = [
        client.get("/documents", headers=headers),
        client.get("/auth/me", headers=headers),
        client.post("/query", json={"question": "anything"}, headers=headers),
    ]
    for response in responses:
        assert response.status_code == 503
        assert response.json()["detail"] == "Authentication service is temporarily unavailable."
        assert "db-host-canary" not in response.text


def test_api_documentation_routes_are_disabled_by_default(api_environment):
    client = api_environment["client"]
    assert [client.get(path).status_code for path in ("/docs", "/redoc", "/openapi.json")] == [404, 404, 404]


def test_api_documentation_routes_can_be_enabled_explicitly(monkeypatch):
    monkeypatch.setenv("EKIP_ACCESS_TOKEN_SECRET", "test-api-signing-secret-over-32-characters")
    monkeypatch.setenv("EKIP_ENABLE_API_DOCS", "true")
    api = _reload_api_module(monkeypatch)
    try:
        client = TestClient(api.app)
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
    finally:
        sys.modules.pop("src.api.main", None)


def test_downloads_are_attachments_with_nosniff(api_environment):
    client = api_environment["client"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    document_id = _upload(client, headers, "download.pdf").json()["document"]["document_id"]
    response = client.get(f"/documents/{document_id}/file", headers=headers)
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-disposition"].startswith("attachment")


def test_validly_signed_tokens_with_mismatched_claims_are_rejected(api_environment):
    from src.auth.access_tokens import decode_access_token, issue_access_token
    from src.auth.service import AuthenticatedPrincipal

    client = api_environment["client"]
    identities = api_environment["identities"]
    headers, _ = auth_headers(api_environment, "admin-a@example.test")
    claims = decode_access_token(headers["Authorization"].split(" ", 1)[1])
    reader_a = identities["reader-a@example.test"]
    admin_b = identities["admin-b@example.test"]

    def forged(user_id, membership_id, organisation_id, family_id):
        principal = AuthenticatedPrincipal(
            user_id,
            membership_id,
            organisation_id,
            Role.ORGANISATION_ADMINISTRATOR,
            permissions_for_role(Role.ORGANISATION_ADMINISTRATOR),
        )
        return {"Authorization": f"Bearer {issue_access_token(principal, family_id).token}"}

    cases = {
        "other organisation": forged(claims.user_id, claims.membership_id, admin_b["organisation"].id, claims.family_id),
        "other user's membership": forged(claims.user_id, reader_a["membership"].id, claims.organisation_id, claims.family_id),
        "other user": forged(reader_a["user"].id, claims.membership_id, claims.organisation_id, claims.family_id),
        "unknown session family": forged(claims.user_id, claims.membership_id, claims.organisation_id, uuid4()),
    }
    assert client.get("/documents", headers=headers).status_code == 200
    for name, forged_headers in cases.items():
        assert client.get("/documents", headers=forged_headers).status_code == 401, name


def test_repeated_failed_logins_are_throttled_without_account_enumeration(api_environment):
    api = api_environment["api"]
    client = api_environment["client"]
    now = [1_000.0]
    api.login_throttle = api.FailureThrottle(clock=lambda: now[0])

    def attempt(email, password="incorrect-password-value", http=client):
        return http.post("/auth/login", json={"email": email, "password": password})

    existing = [attempt("admin-a@example.test") for _ in range(6)]
    unknown = [attempt("nobody@example.test") for _ in range(6)]
    assert [response.status_code for response in existing] == [401] * 5 + [429]
    assert [response.status_code for response in unknown] == [401] * 5 + [429]
    assert existing[-1].json() == unknown[-1].json() == {"detail": "Too many sign-in attempts. Try again later."}
    assert existing[-1].headers["retry-after"] == unknown[-1].headers["retry-after"]
    assert int(existing[-1].headers["retry-after"]) >= 1
    assert attempt("admin-a@example.test", VALID_PASSWORD).status_code == 429
    other_address = TestClient(api.app, client=("198.51.100.7", 50000))
    assert attempt("admin-a@example.test", VALID_PASSWORD, http=other_address).status_code == 200
    now[0] += 3600
    assert attempt("admin-a@example.test", VALID_PASSWORD).status_code == 200


def test_refresh_failures_are_throttled_but_same_key_retries_are_not(api_environment):
    api = api_environment["api"]
    client = api_environment["client"]
    now = [1_000.0]
    api.refresh_throttle = api.FailureThrottle(free_failures=10, clock=lambda: now[0])
    result = login(api_environment, "admin-a@example.test")
    rotation_key = "K" * 43
    body = {"refresh_token": result["refresh_token"], "rotation_key": rotation_key}
    first = client.post("/auth/refresh", json=body)
    assert first.status_code == 200
    retries = [client.post("/auth/refresh", json=body) for _ in range(12)]
    assert [response.status_code for response in retries] == [200] * 12
    assert {response.json()["refresh_token"] for response in retries} == {first.json()["refresh_token"]}
    invalid = [
        client.post("/auth/refresh", json={"refresh_token": f"invalid-token-{index}", "rotation_key": rotation_key})
        for index in range(11)
    ]
    assert [response.status_code for response in invalid] == [401] * 10 + [429]
    assert invalid[-1].json() == {"detail": "Too many sign-in attempts. Try again later."}
