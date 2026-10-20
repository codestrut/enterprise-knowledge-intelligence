"""Exercise the authenticated /query route with real tenant indexes and a fake LLM.

This test uses synthetic in-memory workspaces and dependency overrides. It does not
connect to PostgreSQL, call OpenAI, read tenant files, or start Docker containers.
"""

from types import SimpleNamespace
from uuid import uuid4

import numpy as np
from fastapi.testclient import TestClient

from src.retrieval.reranked_retriever import RerankedRetriever


class FakeEmbedder:
    """Deterministic two-dimensional query embeddings for synthetic canaries."""

    def embed_text(self, text):
        normalized = text.lower()
        if "alpha" in normalized:
            return np.array([1.0, 0.0], dtype=np.float32)
        if "beta" in normalized:
            return np.array([0.0, 1.0], dtype=np.float32)
        return np.array([0.5, 0.5], dtype=np.float32)


class FakeReranker:
    """Keep actual FAISS/BM25 results while passing the evidence threshold."""

    def rerank(self, query, documents, top_k=5):
        return [
            {**document, "score": 5.0}
            for document in documents[:top_k]
        ]


class FakeLLMClient:
    """Return a deterministic cited answer without external model calls."""

    def __init__(self, *args, **kwargs):
        pass

    def generate(self, prompt):
        return "The retrieved source supports this synthetic test answer. [Source 1]"


class FakeGroundingEvaluator:
    def evaluate(self, answer, source_map, source_documents):
        return [{"claim": "synthetic test answer", "status": "grounded"}]


def _chunk(document_id, organisation_id, text):
    return {
        "text": text,
        "metadata": {
            "document_id": document_id,
            "chunk_id": 0,
            "chunk_key": f"{document_id}:0",
            "organisation_id": str(organisation_id),
            "source": f"{document_id}.pdf",
            "page": 1,
        },
    }


def test_authenticated_query_uses_only_the_current_tenant_workspace(
    tmp_path, monkeypatch
):
    # Import the API only after replacing the embedder constructor. Importing the
    # application normally creates its shared embedder, which this test does not need.
    import src.knowledge_base as knowledge_base_module

    embedder = FakeEmbedder()
    reranker = FakeReranker()
    monkeypatch.setattr(knowledge_base_module, "Embedder", lambda: embedder)

    import src.rag_pipeline as rag_pipeline_module

    monkeypatch.setattr(rag_pipeline_module, "LLMClient", FakeLLMClient)

    from src.api import main as api_main
    from src.api.tenant_storage import TenantWorkspaceRegistry
    from src.auth.permissions import Permission
    from src.knowledge_base import KnowledgeBase
    from src.rag_pipeline import RAGPipeline

    alpha_org = uuid4()
    beta_org = uuid4()
    alpha_chunk = _chunk(
        "alpha-canary-doc", alpha_org, "alpha canary confidential project"
    )
    beta_chunk = _chunk(
        "beta-canary-doc", beta_org, "beta canary confidential project"
    )

    registry = TenantWorkspaceRegistry(
        tmp_path / "isolated-tenants",
        shared_embedder=embedder,
        shared_reranker=reranker,
        pipeline_dependencies={"grounding_evaluator": FakeGroundingEvaluator()},
        knowledge_base_factory=KnowledgeBase,
        pipeline_factory=RAGPipeline,
    )
    for org_id, chunk, embedding in (
        (alpha_org, alpha_chunk, [1.0, 0.0]),
        (beta_org, beta_chunk, [0.0, 1.0]),
    ):
        workspace = registry.workspace_for(org_id)
        workspace.knowledge_base.chunks = [chunk]
        workspace.knowledge_base.retriever = RerankedRetriever(
            chunks=[chunk],
            embeddings=np.array([embedding], dtype=np.float32),
            embedder=embedder,
            reranker=reranker,
        )

    monkeypatch.setattr(api_main, "tenant_workspaces", registry)

    selected_org = {"id": alpha_org}

    def fake_authenticated_context():
        return SimpleNamespace(
            principal=SimpleNamespace(
                user_id=uuid4(),
                membership_id=uuid4(),
                organisation_id=selected_org["id"],
                role="organisation_administrator",
                permissions={Permission.DOCUMENTS_QUERY},
            ),
            family_id=uuid4(),
        )

    monkeypatch.setitem(
        api_main.app.dependency_overrides,
        api_main.get_authenticated_context,
        fake_authenticated_context,
    )
    monkeypatch.setitem(
        api_main.app.dependency_overrides,
        api_main.get_auth_db,
        lambda: object(),
    )

    audit_records = []

    def fake_start_audit(_db, context, *, event_type, target_type=None,
                         target_id=None, details=None):
        record = {
            "organisation_id": context.principal.organisation_id,
            "event_type": event_type,
            "target_type": target_type,
            "outcome": "started",
        }
        audit_records.append(record)
        return SimpleNamespace(details={"outcome": "started"}, record=record)

    def fake_finish_audit(_db, event, *, outcome, reason=None):
        event.record["outcome"] = outcome
        if reason is not None:
            event.record["reason"] = reason

    monkeypatch.setattr(api_main, "_start_audit_event", fake_start_audit)
    monkeypatch.setattr(api_main, "_finish_audit_event", fake_finish_audit)

    # Do not use TestClient as a context manager: that would invoke application
    # startup and restore the real process-level workspace registry.
    client = TestClient(api_main.app)

    alpha_response = client.post(
        "/query", json={"question": "alpha canary", "top_k": 5}
    )
    assert alpha_response.status_code == 200, alpha_response.text
    alpha_sources = alpha_response.json()["sources"]
    assert {item["metadata"]["document_id"] for item in alpha_sources} == {
        "alpha-canary-doc"
    }

    selected_org["id"] = beta_org
    beta_response = client.post(
        "/query", json={"question": "beta canary", "top_k": 5}
    )
    assert beta_response.status_code == 200, beta_response.text
    beta_sources = beta_response.json()["sources"]
    assert {item["metadata"]["document_id"] for item in beta_sources} == {
        "beta-canary-doc"
    }

    assert "beta-canary-doc" not in {
        item["metadata"]["document_id"] for item in alpha_sources
    }
    assert "alpha-canary-doc" not in {
        item["metadata"]["document_id"] for item in beta_sources
    }
    assert [record["organisation_id"] for record in audit_records] == [
        alpha_org,
        beta_org,
    ]
    assert all(record["event_type"] == "knowledge.query" for record in audit_records)
    assert all(record["outcome"] == "success" for record in audit_records)
