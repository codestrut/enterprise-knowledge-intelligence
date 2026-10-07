"""Tests for the cross-encoder reranker."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.reranker import Reranker


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_reranker():
    """Verify the cross-encoder reranker returns ranked candidates."""

    documents = load_pdf(PDF_PATH)

    embedder = Embedder()

    chunks = chunk_documents(
        documents,
        tokenizer=embedder.model.tokenizer,
        chunk_size=200,
        overlap=30,
    )

    reranker = Reranker()

    query = "What is GV.RR-01?"

    candidate_ids = [29, 30, 28, 25, 6]

    candidates = [
        chunks[chunk_id]
        for chunk_id in candidate_ids
    ]

    results = reranker.rerank(
        query,
        candidates,
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