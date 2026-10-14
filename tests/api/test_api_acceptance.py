"""Fast, model-free API acceptance tests for the EKIP MVP flow."""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class FakeKnowledgeBase:
    """In-memory stand-in; these tests exercise the API contract, not ML."""

    def __init__(self):
        self.documents = {}
        self.chunks = []
        self.retriever = object()

    def add_pdf(self, file_path, document_id=None):
        path = Path(file_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(str(path))
        document_id = document_id or "test-document"
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
        self.chunks = [
            chunk for chunk in self.chunks
            if chunk.get("metadata", {}).get("document_id") != document_id
        ]
        return record.copy()


class FakePipeline:
    def __init__(self, knowledge_base=None):
        self.knowledge_base = knowledge_base

    def query(self, question, top_k=5):
        if question == "raise-value-error":
            raise ValueError("Question cannot be processed.")
        return {
            "question": question,
            "answer": "A test answer grounded in the uploaded source. [Source 1]",
            "sources": [{"source_number": 1, "text": "Synthetic test evidence."}],
            "invalid_citations": [],
            "refused": False,
            "top_k": top_k,
        }


@pytest.fixture
def api_client(monkeypatch, tmp_path):
    # Stub modules before importing the API module, so this suite needs only
    # the web/API dependencies: no embedding or language model is imported.
    knowledge_base_module = types.ModuleType("src.knowledge_base")
    knowledge_base_module.KnowledgeBase = FakeKnowledgeBase
    rag_pipeline_module = types.ModuleType("src.rag_pipeline")
    rag_pipeline_module.RAGPipeline = FakePipeline
    monkeypatch.setitem(sys.modules, "src.knowledge_base", knowledge_base_module)
    monkeypatch.setitem(sys.modules, "src.rag_pipeline", rag_pipeline_module)
    sys.modules.pop("src.api.main", None)
    api = importlib.import_module("src.api.main")

    uploads = tmp_path / "uploads"
    uploads.mkdir()
    manifest = tmp_path / "documents_manifest.json"
    monkeypatch.setattr(api, "UPLOAD_DIRECTORY", uploads)
    monkeypatch.setattr(api, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(api, "_restore_knowledge_base", lambda: None)

    with TestClient(api.app) as client:
        yield client, api, uploads, manifest

    sys.modules.pop("src.api.main", None)


def _valid_fake_pdf():
    # The endpoint currently validates a PDF signature; indexing is mocked.
    return b"%PDF-1.4\n% EKIP API acceptance test\n"


def test_health_and_empty_document_list(api_client):
    client, _, _, _ = api_client
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["document_count"] == 0

    listed = client.get("/documents")
    assert listed.status_code == 200
    assert listed.json() == {"count": 0, "documents": []}


def test_upload_query_list_and_delete_document_end_to_end(api_client):
    client, _, uploads, manifest_path = api_client

    uploaded = client.post(
        "/documents",
        files={"file": ("NIST Test.pdf", _valid_fake_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    payload = uploaded.json()
    document = payload["document"]
    document_id = document["document_id"]
    assert document["filename"] == "NIST Test.pdf"
    assert document["status"] == "indexed"
    assert (uploads / f"{document_id}.pdf").is_file()

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert document_id in persisted["documents"]
    assert persisted["documents"][document_id]["filename"] == "NIST Test.pdf"

    listed = client.get("/documents").json()
    assert listed["count"] == 1
    assert listed["documents"][0]["document_id"] == document_id

    answer = client.post("/query", json={"question": "What is the test policy?", "top_k": 3})
    assert answer.status_code == 200, answer.text
    assert answer.json()["question"] == "What is the test policy?"
    assert answer.json()["refused"] is False
    assert answer.json()["top_k"] == 3

    deleted = client.delete(f"/documents/{document_id}")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["file_deleted"] is True
    assert not (uploads / f"{document_id}.pdf").exists()
    assert document_id not in json.loads(manifest_path.read_text(encoding="utf-8"))["documents"]
    assert client.get("/documents").json() == {"count": 0, "documents": []}


def test_upload_rejects_non_pdf_and_invalid_pdf_signature(api_client):
    client, _, uploads, _ = api_client

    wrong_extension = client.post(
        "/documents",
        files={"file": ("notes.txt", b"not a pdf", "text/plain")},
    )
    assert wrong_extension.status_code == 400

    wrong_signature = client.post(
        "/documents",
        files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
    )
    assert wrong_signature.status_code == 400
    assert list(uploads.iterdir()) == []


def test_query_validation_and_pipeline_value_error(api_client):
    client, _, _, _ = api_client

    empty_question = client.post("/query", json={"question": ""})
    assert empty_question.status_code == 422

    invalid_top_k = client.post("/query", json={"question": "hello", "top_k": 100})
    assert invalid_top_k.status_code == 422

    pipeline_error = client.post("/query", json={"question": "raise-value-error"})
    assert pipeline_error.status_code == 400


def test_delete_unknown_document_returns_404(api_client):
    client, _, _, _ = api_client
    response = client.delete("/documents/not-present")
    assert response.status_code == 404
