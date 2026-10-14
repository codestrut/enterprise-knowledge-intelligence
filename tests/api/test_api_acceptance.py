"""Fast, model-free API acceptance tests for the EKIP MVP flow."""

import importlib
import json
import sys
import threading
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
    # Keep the real startup restore reachable for the restore tests below.
    monkeypatch.setattr(
        api,
        "_real_restore_knowledge_base",
        api._restore_knowledge_base,
        raising=False,
    )
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


def test_responses_and_manifest_do_not_expose_server_paths(api_client):
    client, _, uploads, manifest_path = api_client

    uploaded = client.post(
        "/documents",
        files={"file": ("a.pdf", _valid_fake_pdf(), "application/pdf")},
    )
    assert uploaded.status_code == 201, uploaded.text
    document = uploaded.json()["document"]
    document_id = document["document_id"]
    assert "source" not in document
    assert "stored_filename" not in document
    assert str(uploads) not in uploaded.text

    listed = client.get("/documents")
    assert "source" not in listed.json()["documents"][0]
    assert str(uploads) not in listed.text

    manifest_text = manifest_path.read_text(encoding="utf-8")
    record = json.loads(manifest_text)["documents"][document_id]
    assert "source" not in record
    assert record["stored_filename"] == f"{document_id}.pdf"
    assert str(uploads) not in manifest_text

    duplicate = client.post(
        "/documents",
        files={"file": ("copy.pdf", _valid_fake_pdf(), "application/pdf")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["existing_document"]["document_id"] == document_id
    assert "source" not in duplicate.json()["detail"]["existing_document"]
    assert str(uploads) not in duplicate.text


def test_restore_keeps_failed_records_and_ignores_stored_absolute_paths(api_client):
    client, api, uploads, manifest_path = api_client
    good_id, bad_id = "good-doc", "missing-doc"
    (uploads / f"{good_id}.pdf").write_bytes(_valid_fake_pdf())
    legacy_dir = "/Users/someone/enterprise/data/uploads"
    manifest_path.write_text(
        json.dumps(
            {
                "documents": {
                    good_id: {
                        "document_id": good_id,
                        "filename": "Good.pdf",
                        "source": f"{legacy_dir}/{good_id}.pdf",
                        "status": "indexed",
                    },
                    bad_id: {
                        "document_id": bad_id,
                        "filename": "Bad.pdf",
                        "source": f"{legacy_dir}/{bad_id}.pdf",
                        "status": "indexed",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    api._real_restore_knowledge_base()

    persisted = json.loads(manifest_path.read_text(encoding="utf-8"))["documents"]
    assert set(persisted) == {good_id, bad_id}
    assert persisted[good_id]["status"] == "indexed"
    assert "source" not in persisted[good_id]
    assert persisted[bad_id]["status"] == "failed"
    assert persisted[bad_id]["error"] == "FileNotFoundError"
    assert "source" not in persisted[bad_id]
    assert good_id in api.knowledge_base.documents
    assert bad_id not in api.knowledge_base.documents
    assert client.get("/health").json()["failed_document_count"] == 1

    removed = client.delete(f"/documents/{bad_id}")
    assert removed.status_code == 200, removed.text
    after = json.loads(manifest_path.read_text(encoding="utf-8"))["documents"]
    assert set(after) == {good_id}
    assert client.delete(f"/documents/{bad_id}").status_code == 404


def test_health_answers_while_the_knowledge_base_is_locked_for_writing(api_client):
    client, api, _, _ = api_client
    holding = threading.Event()
    release = threading.Event()
    result = {}

    def hold_write_lock():
        with api.knowledge_base_lock.write_lock():
            holding.set()
            release.wait(10)

    def probe():
        result["status"] = client.get("/health").status_code

    holder = threading.Thread(target=hold_write_lock, daemon=True)
    holder.start()
    assert holding.wait(5)
    probe_thread = threading.Thread(target=probe, daemon=True)
    probe_thread.start()

    try:
        probe_thread.join(timeout=5)
        answered = "status" in result  # checked before the lock is released
    finally:
        release.set()
    holder.join(5)

    assert answered, "/health blocked on the knowledge-base lock"
    assert result["status"] == 200


def test_queries_run_concurrently(api_client, monkeypatch):
    client, api, _, _ = api_client
    barrier = threading.Barrier(2, timeout=5)

    class BarrierPipeline:
        def query(self, question, top_k=5):
            barrier.wait()  # passes only if both queries are inside at once
            return {
                "question": question,
                "answer": "ok",
                "sources": [],
                "invalid_citations": [],
                "refused": False,
                "top_k": top_k,
            }

    monkeypatch.setattr(api, "pipeline", BarrierPipeline())
    statuses = []

    def ask():
        statuses.append(client.post("/query", json={"question": "q"}).status_code)

    threads = [threading.Thread(target=ask, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(15)

    assert statuses == [200, 200]
