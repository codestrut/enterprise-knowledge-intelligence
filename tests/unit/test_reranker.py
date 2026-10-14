"""Tests for the cross-encoder reranker."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.reranker import Reranker
from src.retrieval.reranked_retriever import RerankedRetriever


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


def test_reranked_retriever_add_documents():
    """Verify newly added documents are available after reranking."""

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

    retriever = RerankedRetriever(
        chunks=initial_chunks,
        embeddings=initial_embeddings,
        embedder=embedder,
    )

    retriever.add_documents(new_chunks)

    assert len(retriever.hybrid_retriever.chunks) == 2
    assert (
        retriever.hybrid_retriever.vector_retriever
        .vector_store.index.ntotal
        == 2
    )
    assert len(
        retriever.hybrid_retriever.bm25_retriever.chunks
    ) == 2

    results = retriever.retrieve(
        "cloud computing infrastructure",
        top_k=1,
        candidate_k=2,
    )

    assert len(results) == 1
    assert results[0]["metadata"]["document_id"] == "document-002"