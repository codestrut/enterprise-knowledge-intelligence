"""Full tenant-scoped RAG lifecycle integration test.

Exercises the real authenticated upload/query routes, PDF extraction, chunking,
SentenceTransformer embeddings, FAISS/BM25 hybrid retrieval, citation mapping,
and tenant workspace restoration. External LLM generation and the NLI decision
are deterministic test doubles; the production RAG pipeline and grounding
orchestration remain active.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


class _DeterministicLLM:
    """Generate only facts found in the retrieved prompt context."""

    def generate(self, prompt: str) -> str:
        context_marker = "CONTEXT:\n"
        question_marker = "\n\nUSER QUESTION:\n"

        if context_marker not in prompt or question_marker not in prompt:
            return "I don't have sufficient evidence in the available knowledge base to answer that question."

        context = prompt.split(context_marker, 1)[1].split(question_marker, 1)[0]

        if "ORBITAL-KESTREL-731" in context:
            return (
                "The ORBITAL-KESTREL-731 protocol stores records for 18 years. "
                "[Source 1]"
            )
        if "EMBER-FOX-284" in context:
            return "The EMBER-FOX-284 system stores reports for 9 years. [Source 1]"
        return "I don't have sufficient evidence in the available knowledge base to answer that question."


class _DeterministicReranker:
    """Keep the real hybrid candidates while stabilising the evidence gate."""

    def rerank(self, query, documents, top_k=5):
        return [
            {"text": item["text"], "metadata": item["metadata"], "score": 5.0}
            for item in documents[:top_k]
        ]


class _DeterministicSemanticGrounder:
    """Control only the NLI model output; retain GroundingEvaluator logic."""

    def check_claim(self, claim, evidence):
        return {
            "label": "entailment",
            "raw_label": "entailment",
            "relation_guard": {"applied": False},
            "support_guard": {"applied": False},
            "probabilities": {
                "contradiction": 0.01,
                "entailment": 0.98,
                "neutral": 0.01,
            },
        }


class _DeterministicClaimDecomposer:
    def decompose(self, claim, context=None):
        return [claim]


def _make_text_pdf(text: str) -> bytes:
    """Build a minimal one-page, text-based PDF without extra dependencies."""
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 11 Tf 50 740 Td ({escaped}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n"
        + stream + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(body)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


@pytest.fixture
def rag_api_harness(tmp_path, monkeypatch):
    """Build an isolated real RAG workspace registry behind the actual API."""
    import src.rag_pipeline as rag_pipeline_module

    monkeypatch.setattr(
        rag_pipeline_module,
        "LLMClient",
        lambda: _DeterministicLLM(),
    )
    monkeypatch.setenv("EKIP_RETRIEVAL_BACKEND", "custom")

    from src.api import main as api_main
    from src.api.tenant_storage import TenantWorkspaceRegistry
    from src.auth.permissions import Permission
    from src.generation.grounding_evaluator import GroundingEvaluator
    from src.knowledge_base import KnowledgeBase
    from src.rag_pipeline import RAGPipeline

    embedder = api_main._shared_embedder
    grounding_evaluator = GroundingEvaluator(
        embedder=embedder,
        semantic_grounder=_DeterministicSemanticGrounder(),
        claim_decomposer=_DeterministicClaimDecomposer(),
    )
    storage_root = tmp_path / "tenant-data"

    def new_registry():
        return TenantWorkspaceRegistry(
            storage_root,
            shared_embedder=embedder,
            shared_reranker=_DeterministicReranker(),
            pipeline_dependencies={"grounding_evaluator": grounding_evaluator},
            knowledge_base_factory=KnowledgeBase,
            pipeline_factory=RAGPipeline,
        )

    registry = new_registry()
    monkeypatch.setattr(api_main, "tenant_workspaces", registry)

    organisation_a = uuid4()
    organisation_b = uuid4()
    selected_organisation = {"id": organisation_a}

    def authenticated_context():
        return SimpleNamespace(
            principal=SimpleNamespace(
                user_id=uuid4(),
                membership_id=uuid4(),
                organisation_id=selected_organisation["id"],
                role="organisation_administrator",
                permissions=frozenset(
                    {
                        Permission.DOCUMENTS_UPLOAD,
                        Permission.DOCUMENTS_QUERY,
                        Permission.DOCUMENTS_READ,
                    }
                ),
            ),
            family_id=uuid4(),
        )

    monkeypatch.setitem(
        api_main.app.dependency_overrides,
        api_main.get_authenticated_context,
        authenticated_context,
    )
    monkeypatch.setitem(
        api_main.app.dependency_overrides,
        api_main.get_auth_db,
        lambda: object(),
    )

    audit_events = []

    def start_audit(_db, context, *, event_type, target_type=None,
                    target_id=None, details=None):
        event = SimpleNamespace(
            details={"outcome": "started"},
            organisation_id=context.principal.organisation_id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
        )
        audit_events.append(event)
        return event

    def finish_audit(_db, event, *, outcome, reason=None):
        event.details["outcome"] = outcome
        if reason:
            event.details["reason"] = reason

    monkeypatch.setattr(api_main, "_start_audit_event", start_audit)
    monkeypatch.setattr(api_main, "_finish_audit_event", finish_audit)

    # Do not enter TestClient as a context manager: that would run application
    # startup and restore the process-level registry outside this isolated test.
    client = TestClient(api_main.app)
    yield SimpleNamespace(
        api=api_main,
        client=client,
        registry=registry,
        new_registry=new_registry,
        selected_organisation=selected_organisation,
        organisation_a=organisation_a,
        organisation_b=organisation_b,
        audit_events=audit_events,
    )
    client.close()


def test_authenticated_pdf_upload_query_restore_and_tenant_isolation(
    rag_api_harness,
):
    harness = rag_api_harness
    canary_a = "ORBITAL-KESTREL-731"
    canary_b = "EMBER-FOX-284"
    pdf_a = _make_text_pdf(
        "The ORBITAL-KESTREL-731 protocol stores records for 18 years."
    )
    pdf_b = _make_text_pdf(
        "The EMBER-FOX-284 system stores reports for 9 years."
    )

    # 1. Upload through the real authenticated API route and real KnowledgeBase.
    upload_a = harness.client.post(
        "/documents",
        files={"file": ("orbital-policy.pdf", pdf_a, "application/pdf")},
    )
    assert upload_a.status_code == 201, upload_a.text
    document_a = upload_a.json()["document"]
    document_a_id = document_a["document_id"]
    assert document_a["status"] == "indexed"
    assert document_a["filename"] == "orbital-policy.pdf"

    workspace_a = harness.registry.workspace_for(harness.organisation_a)
    assert len(workspace_a.knowledge_base.chunks) >= 1
    assert workspace_a.knowledge_base.retriever is not None
    assert workspace_a.manifest_path.is_file()
    assert (workspace_a.upload_directory / f"{document_a_id}.pdf").is_file()

    # 2. Query through the real API and RAGPipeline. FAISS/BM25 and embeddings
    # are real; only external generation, reranker scoring and NLI output are fixed.
    query_a = harness.client.post(
        "/query",
        json={"question": f"What is the retention period for {canary_a}?", "top_k": 5},
    )
    assert query_a.status_code == 200, query_a.text
    result_a = query_a.json()
    assert canary_a in result_a["answer"]
    assert "18 years" in result_a["answer"]
    assert result_a["refused"] is False
    assert result_a["invalid_citations"] == []
    assert result_a["citations"]
    assert result_a["citations"][0]["page"] == 1
    assert result_a["citations"][0]["source"] == "orbital-policy.pdf"
    assert result_a["evidence"]["sufficient"] is True
    assert {item["metadata"]["document_id"] for item in result_a["sources"]} == {
        document_a_id
    }
    assert result_a["sources"][0]["metadata"]["filename"] == "orbital-policy.pdf"

    # 3. Upload a different document to a second organisation through the same API.
    harness.selected_organisation["id"] = harness.organisation_b
    upload_b = harness.client.post(
        "/documents",
        files={"file": ("ember-policy.pdf", pdf_b, "application/pdf")},
    )
    assert upload_b.status_code == 201, upload_b.text
    document_b_id = upload_b.json()["document"]["document_id"]

    query_b = harness.client.post(
        "/query",
        json={"question": f"What is the retention period for {canary_b}?", "top_k": 5},
    )
    assert query_b.status_code == 200, query_b.text
    result_b = query_b.json()
    assert canary_b in result_b["answer"]
    assert "9 years" in result_b["answer"]
    assert {item["metadata"]["document_id"] for item in result_b["sources"]} == {
        document_b_id
    }

    # 4. Simulate application restart: discard the registry and reconstruct all
    # tenant workspaces from their own persisted PDF files and manifests.
    restored_registry = harness.new_registry()
    restored_registry.restore_all()
    harness.api.tenant_workspaces = restored_registry

    restored_a = restored_registry.workspace_for(harness.organisation_a)
    assert document_a_id in restored_a.knowledge_base.documents
    assert restored_a.knowledge_base.documents[document_a_id]["status"] == "indexed"
    assert restored_a.knowledge_base.documents[document_a_id]["filename"] == "orbital-policy.pdf"
    assert any(
        chunk["metadata"].get("document_id") == document_a_id
        for chunk in restored_a.knowledge_base.chunks
    )

    harness.selected_organisation["id"] = harness.organisation_a
    restored_query = harness.client.post(
        "/query",
        json={"question": f"What is the retention period for {canary_a}?", "top_k": 5},
    )
    assert restored_query.status_code == 200, restored_query.text
    restored_result = restored_query.json()
    assert canary_a in restored_result["answer"]
    assert "18 years" in restored_result["answer"]
    assert restored_result["citations"]
    assert restored_result["citations"][0]["source"] == "orbital-policy.pdf"
    assert {item["metadata"]["document_id"] for item in restored_result["sources"]} == {
        document_a_id
    }

    # 5. Cross-tenant query: organisation B must only receive its own source,
    # even when asking for organisation A's unique canary.
    harness.selected_organisation["id"] = harness.organisation_b
    cross_tenant_query = harness.client.post(
        "/query",
        json={"question": f"What is the retention period for {canary_a}?", "top_k": 5},
    )
    assert cross_tenant_query.status_code == 200, cross_tenant_query.text
    cross_result = cross_tenant_query.json()
    returned_document_ids = {
        item["metadata"]["document_id"] for item in cross_result["sources"]
    }
    assert returned_document_ids == {document_b_id}
    assert canary_a not in cross_result["answer"]
    assert canary_a not in " ".join(item["text"] for item in cross_result["sources"])

    # Audit events remain associated with the authenticated tenant scope.
    assert [event.organisation_id for event in harness.audit_events] == [
        harness.organisation_a,
        harness.organisation_a,
        harness.organisation_b,
        harness.organisation_b,
        harness.organisation_a,
        harness.organisation_b,
    ]
    assert all(event.details["outcome"] == "success" for event in harness.audit_events)

