"""Tests for hybrid FAISS + BM25 retrieval."""

import numpy as np

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.hybrid_retriever import HybridRetriever


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_hybrid_retrieval():
    """Verify hybrid retrieval returns ranked results."""

    documents = load_pdf(PDF_PATH)
    embedder = Embedder()

    chunks = chunk_documents(
        documents,
        tokenizer=embedder.model.tokenizer,
        chunk_size=200,
        overlap=30,
    )

    embeddings = embedder.embed_documents(chunks)

    retriever = HybridRetriever(
        chunks=chunks,
        embeddings=embeddings,
        embedder=embedder,
    )

    results = retriever.retrieve(
        "What is GV.RR-01?",
        top_k=5,
    )

    assert len(results) == 5

    assert all(
        "text" in result
        and "metadata" in result
        and "score" in result
        for result in results
    )

    assert all(
        "chunk_id" in result["metadata"]
        for result in results
    )


def test_hybrid_add_documents():
    """Verify newly added chunks are searchable through hybrid retrieval."""

    embedder = Embedder()

    initial_chunks = [
        {
            "text": (
                "Cybersecurity risk management protects "
                "organizational assets."
            ),
            "metadata": {
                "document_id": "document-001",
                "chunk_id": 0,
                "chunk_key": "document-001:0",
            },
        }
    ]

    new_chunks = [
        {
            "text": "Cloud computing provides scalable infrastructure.",
            "metadata": {
                "document_id": "document-002",
                "chunk_id": 0,
                "chunk_key": "document-002:0",
            },
        }
    ]

    initial_embeddings = embedder.embed_documents(initial_chunks)

    retriever = HybridRetriever(
        chunks=initial_chunks,
        embeddings=initial_embeddings,
        embedder=embedder,
    )

    retriever.add_documents(new_chunks)

    assert len(retriever.chunks) == 2
    assert len(retriever.vector_retriever.chunks) == 2
    assert len(retriever.bm25_retriever.chunks) == 2
    assert retriever.vector_retriever.vector_store.index.ntotal == 2

    results = retriever.retrieve(
        "cloud computing infrastructure",
        top_k=1,
        candidate_k=2,
    )

    assert len(results) == 1
    assert results[0]["metadata"]["document_id"] == "document-002"


def test_hybrid_retrieval_uses_unique_chunk_keys():
    """Ensure equal local chunk IDs do not collide across documents."""

    embedder = Embedder()

    chunks = [
        {
            "text": "Cybersecurity risk management protects assets.",
            "metadata": {
                "document_id": "document-001",
                "chunk_id": 0,
                "chunk_key": "document-001:0",
            },
        },
        {
            "text": "Cloud computing provides scalable infrastructure.",
            "metadata": {
                "document_id": "document-002",
                "chunk_id": 0,
                "chunk_key": "document-002:0",
            },
        },
    ]

    embeddings = embedder.embed_documents(chunks)

    retriever = HybridRetriever(
        chunks=chunks,
        embeddings=embeddings,
        embedder=embedder,
    )

    results = retriever.retrieve(
        "cloud computing infrastructure",
        top_k=2,
        candidate_k=2,
    )

    result_keys = {
        result["metadata"]["chunk_key"]
        for result in results
    }

    assert len(results) == 2
    assert result_keys == {
        "document-001:0",
        "document-002:0",
    }


def test_rebuild_excluding_document_preserves_remaining_indexes():
    """Verify deletion rebuilds vector and BM25 indexes consistently."""

    embedder = Embedder()

    chunks = [
        {
            "text": "Cybersecurity risk management protects organizational assets.",
            "metadata": {
                "document_id": "document-001",
                "chunk_id": 0,
                "chunk_key": "document-001:0",
            },
        },
        {
            "text": "Cloud computing provides scalable infrastructure.",
            "metadata": {
                "document_id": "document-002",
                "chunk_id": 0,
                "chunk_key": "document-002:0",
            },
        },
    ]

    embeddings = embedder.embed_documents(chunks)

    retriever = HybridRetriever(
        chunks=chunks,
        embeddings=embeddings,
        embedder=embedder,
    )

    replacement = retriever.rebuild_excluding_document("document-001")

    assert replacement is not None
    assert len(replacement.chunks) == 1
    assert len(replacement.vector_retriever.chunks) == 1
    assert len(replacement.bm25_retriever.chunks) == 1
    assert replacement.vector_retriever.vector_store.index.ntotal == 1

    assert replacement.chunks[0]["metadata"]["document_id"] == "document-002"

    results = replacement.retrieve(
        "cloud computing infrastructure",
        top_k=1,
        candidate_k=1,
    )

    assert len(results) == 1
    assert results[0]["metadata"]["document_id"] == "document-002"


def test_rebuild_excluding_last_document_returns_none():
    """Verify removing the final document produces no replacement index."""

    embedder = Embedder()

    chunks = [
        {
            "text": "Cybersecurity risk management protects assets.",
            "metadata": {
                "document_id": "document-001",
                "chunk_id": 0,
                "chunk_key": "document-001:0",
            },
        }
    ]

    embeddings = embedder.embed_documents(chunks)

    retriever = HybridRetriever(
        chunks=chunks,
        embeddings=embeddings,
        embedder=embedder,
    )

    replacement = retriever.rebuild_excluding_document("document-001")

    assert replacement is None
