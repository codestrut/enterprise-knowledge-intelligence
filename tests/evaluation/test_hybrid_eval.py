"""Evaluate hybrid retrieval using vector search and BM25."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.evaluation.retrieval_eval import (
    EVALUATION_DATASET,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
    resolve_relevant_chunks,
)
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.hybrid_retriever import HybridRetriever


PDF_PATH = "data/raw/nist_csf_2.0.pdf"
K_VALUES = [1, 3, 5]


def test_hybrid_retrieval_evaluation():
    """Evaluate hybrid retrieval against the benchmark dataset."""

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

    results = []

    for item in EVALUATION_DATASET:

        relevant_chunks = resolve_relevant_chunks(
            chunks,
            item["relevant_chunks"],
        )

        if not relevant_chunks:
            continue

        retrieved_results = retriever.retrieve(
            item["query"],
            top_k=max(K_VALUES),
            candidate_k=10,
        )

        retrieved_chunks = [
            result["metadata"]["chunk_id"]
            for result in retrieved_results
        ]

        results.append({
            "query": item["query"],
            "retrieved_chunks": retrieved_chunks,
            "relevant_chunks": relevant_chunks,
        })

    assert results

    for k in K_VALUES:

        hit_scores = [
            hit_at_k(
                result["retrieved_chunks"],
                result["relevant_chunks"],
                k,
            )
            for result in results
        ]

        recall_scores = [
            recall_at_k(
                result["retrieved_chunks"],
                result["relevant_chunks"],
                k,
            )
            for result in results
        ]

        hit_rate = sum(hit_scores) / len(hit_scores)
        recall = sum(recall_scores) / len(recall_scores)

        assert 0.0 <= hit_rate <= 1.0
        assert 0.0 <= recall <= 1.0

    mrr_scores = [
        reciprocal_rank(
            result["retrieved_chunks"],
            result["relevant_chunks"],
        )
        for result in results
    ]

    mrr = sum(mrr_scores) / len(mrr_scores)

    assert 0.0 <= mrr <= 1.0