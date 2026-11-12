from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.api.tenant_storage import TenantWorkspaceRegistry
from src.api.shared_inference import SharedGroundingEvaluator, SharedReranker
import src.knowledge_base as knowledge_base_module
from src.knowledge_base import KnowledgeBase


class FakeKnowledgeBase:
    def __init__(self, embedder=None, reranker=None):
        self.embedder = embedder
        self.reranker = reranker
        self.tenant_id = None
        self.documents = {}
        self.chunks = []

    def add_pdf(self, file_path, document_id):
        path = Path(file_path)
        record = {
            "document_id": document_id,
            "filename": path.name,
            "source": str(path),
            "status": "indexed",
            "chunk_count": 1,
        }
        self.documents[document_id] = record
        self.chunks.append({"metadata": {"document_id": document_id}})
        return record.copy()


class FakePipeline:
    def __init__(self, knowledge_base):
        self.knowledge_base = knowledge_base


def registry(root, embedder=None, reranker=None):
    return TenantWorkspaceRegistry(
        root,
        shared_embedder=embedder or object(),
        shared_reranker=reranker,
        pipeline_dependencies={},
        knowledge_base_factory=FakeKnowledgeBase,
        pipeline_factory=FakePipeline,
    )


def test_workspaces_have_distinct_indexes_paths_and_shared_embedder(tmp_path):
    shared_embedder = object()
    shared_reranker = object()
    store = registry(tmp_path, shared_embedder, shared_reranker)
    organisation_a, organisation_b = uuid4(), uuid4()

    first = store.workspace_for(organisation_a)
    second = store.workspace_for(organisation_b)

    assert first is not second
    assert first.knowledge_base is not second.knowledge_base
    assert first.knowledge_base.embedder is shared_embedder
    assert second.knowledge_base.embedder is shared_embedder
    assert first.knowledge_base.reranker is shared_reranker
    assert second.knowledge_base.reranker is shared_reranker
    assert first.knowledge_base is not second.knowledge_base
    assert first.root != second.root
    assert first.upload_directory.parent == first.root
    assert second.upload_directory.parent == second.root


def test_restore_only_reads_each_uuid_directory_and_keeps_legacy_files_quarantined(tmp_path):
    organisation_a, organisation_b = uuid4(), uuid4()
    store = registry(tmp_path)
    a = store.workspace_for(organisation_a)
    b = store.workspace_for(organisation_b)
    doc_a, doc_b = str(uuid4()), str(uuid4())
    (a.upload_directory / f"{doc_a}.pdf").write_bytes(b"test-a")
    (b.upload_directory / f"{doc_b}.pdf").write_bytes(b"test-b")
    a.write_manifest({doc_a: {"document_id": doc_a, "filename": "A.pdf", "status": "indexed"}})
    b.write_manifest({doc_b: {"document_id": doc_b, "filename": "B.pdf", "status": "indexed"}})
    legacy = tmp_path / "legacy-shared"
    legacy.mkdir()
    (legacy / "documents_manifest.json").write_text("do not open", encoding="utf-8")

    restarted = registry(tmp_path)
    restarted.restore_all()
    restored_a = restarted.workspace_for(organisation_a)
    restored_b = restarted.workspace_for(organisation_b)

    assert set(restored_a.knowledge_base.documents) == {doc_a}
    assert set(restored_b.knowledge_base.documents) == {doc_b}
    assert (legacy / "documents_manifest.json").read_text() == "do not open"


def test_workspace_ids_reject_path_traversal_and_symlink_escape(tmp_path):
    store = registry(tmp_path / "tenants")
    with pytest.raises(ValueError, match="Invalid organisation scope"):
        store.workspace_for("../outside")

    outside = tmp_path / "outside"
    outside.mkdir()
    organisation_id = uuid4()
    (store.root / str(organisation_id)).parent.mkdir(parents=True, exist_ok=True)
    (store.root / str(organisation_id)).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="Tenant storage path is invalid"):
        store.workspace_for(organisation_id)
    assert list(outside.iterdir()) == []


def test_tenant_rag_metadata_uses_safe_source_basename(tmp_path, monkeypatch):
    source = tmp_path / "private" / "tenant-safe.pdf"
    source.parent.mkdir()
    source.write_bytes(b"synthetic test pdf")
    organisation_id = uuid4()
    embedder = SimpleNamespace(
        model=SimpleNamespace(tokenizer=object()),
        embed_documents=lambda chunks: [[0.0] for _ in chunks],
    )
    monkeypatch.setattr(
        knowledge_base_module,
        "load_pdf",
        lambda _path: [{"text": "test content", "metadata": {"source": str(source), "page": 1}}],
    )
    monkeypatch.setattr(
        knowledge_base_module,
        "chunk_documents",
        lambda pages, **_kwargs: [{"text": pages[0]["text"], "metadata": pages[0]["metadata"].copy()}],
    )
    monkeypatch.setattr(knowledge_base_module, "RerankedRetriever", lambda **_kwargs: object())

    workspace = KnowledgeBase(embedder=embedder, tenant_id=organisation_id)
    workspace.add_pdf(source, document_id=str(uuid4()))

    metadata = workspace.chunks[0]["metadata"]
    assert metadata["source"] == "tenant-safe.pdf"
    assert metadata["organisation_id"] == str(organisation_id)
    assert str(source.parent) not in str(metadata)


def test_expensive_reranker_and_grounder_are_lazily_shared():
    created = {"reranker": 0, "grounder": 0}

    class Component:
        def __init__(self, key):
            self.key = key

        def rerank(self, query, documents, top_k=5):
            return [(query, len(documents), top_k)]

        def evaluate(self, claim):
            return (claim, self.key)

    def reranker_factory():
        created["reranker"] += 1
        return Component("reranker")

    def grounder_factory():
        created["grounder"] += 1
        return Component("grounder")

    reranker = SharedReranker(reranker_factory)
    grounder = SharedGroundingEvaluator(grounder_factory)
    assert created == {"reranker": 0, "grounder": 0}
    assert reranker.rerank("q", [1], top_k=3) == [("q", 1, 3)]
    assert reranker.rerank("q2", [], top_k=2) == [("q2", 0, 2)]
    assert grounder.evaluate("claim-a") == ("claim-a", "grounder")
    assert grounder.evaluate("claim-b") == ("claim-b", "grounder")
    assert created == {"reranker": 1, "grounder": 1}


def test_shared_grounding_evaluator_delegates_predecomposed_evaluation():
    created = {"count": 0}
    calls = []

    class Evaluator:
        def evaluate(self, *args, **kwargs):
            calls.append(("evaluate", args, kwargs))
            return "regular"

        def evaluate_predecomposed(self, *args, **kwargs):
            calls.append(("predecomposed", args, kwargs))
            return "predecomposed"

    def factory():
        created["count"] += 1
        return Evaluator()

    shared = SharedGroundingEvaluator(factory)

    assert shared.evaluate_predecomposed("answer", {"1": 0}, []) == "predecomposed"
    assert shared.evaluate_predecomposed("answer-2", {"2": 1}, []) == "predecomposed"
    assert shared.evaluate("regular-answer") == "regular"

    assert created["count"] == 1
    assert [call[0] for call in calls] == [
        "predecomposed",
        "predecomposed",
        "evaluate",
    ]


def test_shared_grounding_evaluator_predecomposed_falls_back_for_legacy_evaluator():
    created = {"count": 0}

    class LegacyEvaluator:
        def evaluate(self, *args, **kwargs):
            return ("legacy", args, kwargs)

    def factory():
        created["count"] += 1
        return LegacyEvaluator()

    shared = SharedGroundingEvaluator(factory)

    result = shared.evaluate_predecomposed("answer", {"1": 0}, [])

    assert result == ("legacy", ("answer", {"1": 0}, []), {})
    assert created["count"] == 1
