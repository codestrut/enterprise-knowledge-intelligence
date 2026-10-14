"""Tests for dynamic knowledge-base management."""

import pytest

from src.knowledge_base import KnowledgeBase


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_knowledge_base_add_and_list_pdf():
    """Verify a PDF can be ingested and listed."""

    knowledge_base = KnowledgeBase()

    record = knowledge_base.add_pdf(
        PDF_PATH,
        document_id="test-nist-001",
    )

    assert record["document_id"] == "test-nist-001"
    assert record["filename"] == "nist_csf_2.0.pdf"
    assert record["page_count"] > 0
    assert record["chunk_count"] > 0
    assert record["status"] == "indexed"

    documents = knowledge_base.list_documents()

    assert len(documents) == 1
    assert documents[0]["document_id"] == "test-nist-001"
    assert len(knowledge_base.chunks) == record["chunk_count"]


def test_knowledge_base_rejects_duplicate_document_id():
    """Verify duplicate document IDs are rejected."""

    knowledge_base = KnowledgeBase()

    knowledge_base.add_pdf(
        PDF_PATH,
        document_id="test-nist-001",
    )

    with pytest.raises(
        ValueError,
        match="Document ID already exists",
    ):
        knowledge_base.add_pdf(
            PDF_PATH,
            document_id="test-nist-001",
        )


def test_knowledge_base_rejects_missing_file(tmp_path):
    """Verify nonexistent PDF paths are rejected."""

    knowledge_base = KnowledgeBase()

    missing_path = tmp_path / "missing.pdf"

    with pytest.raises(FileNotFoundError):
        knowledge_base.add_pdf(str(missing_path))



class FakeHybridRetriever:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def rebuild_excluding_document(self, document_id):
        remaining = [
            chunk for chunk in self.chunks
            if chunk["metadata"].get("document_id") != document_id
        ]
        return FakeHybridRetriever(remaining) if remaining else None


class FakeRerankedRetriever:
    def __init__(self, chunks):
        self.hybrid_retriever = FakeHybridRetriever(chunks)


def make_test_chunk(document_id, chunk_id=0):
    return {
        "text": f"Content from {document_id}",
        "metadata": {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "chunk_key": f"{document_id}:{chunk_id}",
        },
    }


def test_delete_document_preserves_remaining_documents():
    knowledge_base = KnowledgeBase(embedder=object())

    first_chunk = make_test_chunk("document-001")
    second_chunk = make_test_chunk("document-002")

    knowledge_base.documents = {
        "document-001": {
            "document_id": "document-001",
            "filename": "first.pdf",
            "chunk_count": 1,
        },
        "document-002": {
            "document_id": "document-002",
            "filename": "second.pdf",
            "chunk_count": 1,
        },
    }
    knowledge_base.chunks = [first_chunk, second_chunk]
    knowledge_base.retriever = FakeRerankedRetriever(
        knowledge_base.chunks
    )

    deleted = knowledge_base.delete_document("document-001")

    assert deleted["document_id"] == "document-001"
    assert list(knowledge_base.documents) == ["document-002"]
    assert [c["metadata"]["document_id"] for c in knowledge_base.chunks] == [
        "document-002"
    ]
    assert knowledge_base.retriever.hybrid_retriever.chunks == [
        second_chunk
    ]


def test_delete_last_document_empties_knowledge_base():
    knowledge_base = KnowledgeBase(embedder=object())

    chunk = make_test_chunk("document-001")

    knowledge_base.documents = {
        "document-001": {
            "document_id": "document-001",
            "filename": "first.pdf",
            "chunk_count": 1,
        }
    }
    knowledge_base.chunks = [chunk]
    knowledge_base.retriever = FakeRerankedRetriever([chunk])

    knowledge_base.delete_document("document-001")

    assert knowledge_base.documents == {}
    assert knowledge_base.chunks == []
    assert knowledge_base.retriever is None


def test_delete_unknown_document_does_not_change_state():
    knowledge_base = KnowledgeBase(embedder=object())

    chunk = make_test_chunk("document-001")
    record = {
        "document_id": "document-001",
        "filename": "first.pdf",
        "chunk_count": 1,
    }

    knowledge_base.documents = {"document-001": record}
    knowledge_base.chunks = [chunk]
    knowledge_base.retriever = FakeRerankedRetriever([chunk])

    with pytest.raises(KeyError, match="Document not found"):
        knowledge_base.delete_document("missing-document")

    assert knowledge_base.documents == {"document-001": record}
    assert knowledge_base.chunks == [chunk]
