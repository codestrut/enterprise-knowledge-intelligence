"""Focused tenant-scoping tests for RAGPipeline; no external LLM/API required."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

import src.rag_pipeline as rag_pipeline_module
from src.rag_pipeline import RAGPipeline


class FakeRetriever:
    """Return only the documents assigned to this tenant's workspace."""

    def __init__(self, documents):
        self.documents = list(documents)
        # RAGPipeline.query inspects these fields for safe diagnostics even
        # when detailed retrieval logging is disabled.
        self.hybrid_retriever = SimpleNamespace(
            chunks=self.documents,
            vector_retriever=SimpleNamespace(
                vector_store=SimpleNamespace(
                    index=SimpleNamespace(ntotal=len(self.documents))
                ),
                chunks=self.documents,
            ),
            bm25_retriever=SimpleNamespace(chunks=self.documents),
        )

    def retrieve(self, question, top_k=5):
        return self.documents[:top_k]


def make_document(tenant_id, marker):
    return {
        "text": f"Synthetic test content for {marker}.",
        "score": 1.0,
        "metadata": {
            "organisation_id": str(tenant_id),
            "document_id": f"doc-{marker.lower()}",
            "filename": f"{marker}.pdf",
            "source": f"{marker}.pdf",
            "page": 1,
        },
    }


def make_pipeline(knowledge_base):
    """Construct only the fields query() needs; no model or embeddings load."""
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.knowledge_base = knowledge_base
    pipeline.retrieval_backend = "custom"
    pipeline._framework_retriever = None
    pipeline._framework_hybrid_source = None
    pipeline.llm = SimpleNamespace(
        generate=lambda _prompt: pytest.fail("Fake LLM should not be called")
    )
    pipeline.grounding_evaluator = None
    return pipeline


def make_knowledge_base(tenant_id, marker):
    document = make_document(tenant_id, marker)
    return SimpleNamespace(
        tenant_id=tenant_id,
        chunks=[document],
        retriever=FakeRetriever([document]),
    )


def test_each_tenant_query_returns_only_its_workspace_documents(monkeypatch):
    """The query path must use each KB's retriever and preserve its tenant ID."""
    tenant_alpha, tenant_beta = uuid4(), uuid4()
    alpha_kb = make_knowledge_base(tenant_alpha, "ALPHA_CANARY")
    beta_kb = make_knowledge_base(tenant_beta, "BETA_CANARY")

    # Keep this test focused on tenant-to-retriever routing, not semantic
    # relevance scoring or answer generation.
    monkeypatch.setattr(
        rag_pipeline_module,
        "check_evidence",
        lambda _documents: {"sufficient": False, "reason": "test_isolation"},
    )

    alpha_result = make_pipeline(alpha_kb).query(
        "show synthetic test content", tenant_id=str(tenant_alpha)
    )
    beta_result = make_pipeline(beta_kb).query(
        "show synthetic test content", tenant_id=str(tenant_beta)
    )

    alpha_sources = alpha_result["sources"]
    beta_sources = beta_result["sources"]

    assert [doc["metadata"]["organisation_id"] for doc in alpha_sources] == [
        str(tenant_alpha)
    ]
    assert [doc["metadata"]["organisation_id"] for doc in beta_sources] == [
        str(tenant_beta)
    ]
    assert "ALPHA_CANARY" in alpha_sources[0]["text"]
    assert "ALPHA_CANARY" not in repr(beta_sources)
    assert "BETA_CANARY" in beta_sources[0]["text"]
    assert "BETA_CANARY" not in repr(alpha_sources)


def test_query_rejects_mismatched_tenant_before_retrieval():
    tenant_alpha, tenant_beta = uuid4(), uuid4()
    alpha_kb = make_knowledge_base(tenant_alpha, "ALPHA_CANARY")
    pipeline = make_pipeline(alpha_kb)

    with pytest.raises(ValueError, match="Tenant context does not match"):
        pipeline.query("show synthetic test content", tenant_id=str(tenant_beta))
