"""Tests for the document retriever."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.retriever import Retriever


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_retriever():
    """Verify the vector retriever returns ranked results."""

    documents = load_pdf(PDF_PATH)
    embedder = Embedder()

    chunks = chunk_documents(
        documents,
        tokenizer=embedder.model.tokenizer,
        chunk_size=200,
        overlap=30,
    )

    embeddings = embedder.embed_documents(chunks)

    retriever = Retriever(
        chunks=chunks,
        embeddings=embeddings,
        embedder=embedder,
    )

    results = retriever.retrieve(
        "What is an Organizational Profile?",
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


def test_retriever_add_documents():
    """Ensure new document chunks can be added incrementally."""

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

    retriever = Retriever(
        chunks=initial_chunks,
        embeddings=initial_embeddings,
        embedder=embedder,
    )

    retriever.add_documents(new_chunks)

    assert len(retriever.chunks) == 2
    assert retriever.vector_store.index.ntotal == 2

    results = retriever.retrieve(
        "cloud computing infrastructure",
        top_k=1,
    )

    assert len(results) == 1
    assert results[0]["metadata"]["document_id"] == "document-002"