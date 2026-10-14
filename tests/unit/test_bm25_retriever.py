"""Tests for BM25 lexical retrieval."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.bm25_retriever import BM25Retriever


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_bm25_retrieval():
    """Verify BM25 retrieves results for known queries."""

    documents = load_pdf(PDF_PATH)
    embedder = Embedder()

    chunks = chunk_documents(
        documents,
        tokenizer=embedder.model.tokenizer,
        chunk_size=200,
        overlap=30,
    )

    retriever = BM25Retriever(chunks)

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


def test_bm25_add_documents():
    """Verify newly added chunks become searchable through BM25."""

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
            "text": (
                "Cloud computing provides scalable infrastructure."
            ),
            "metadata": {
                "document_id": "document-002",
                "chunk_id": 0,
                "chunk_key": "document-002:0",
            },
        }
    ]

    retriever = BM25Retriever(initial_chunks)

    retriever.add_documents(new_chunks)

    assert len(retriever.chunks) == 2

    results = retriever.retrieve(
        "cloud computing infrastructure",
        top_k=1,
    )

    assert len(results) == 1
    assert results[0]["metadata"]["document_id"] == "document-002"