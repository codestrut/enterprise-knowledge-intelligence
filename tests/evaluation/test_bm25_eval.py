"""Evaluate BM25 retrieval."""

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.retrieval.bm25_retriever import BM25Retriever
from src.evaluation.retrieval_eval import (
    EVALUATION_DATASET,
    resolve_relevant_chunks,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
)


PDF_PATH = "data/raw/nist_csf_2.0.pdf"
K_VALUES = [1, 3, 5]


documents = load_pdf(PDF_PATH)

embedder = Embedder()

chunks = chunk_documents(
    documents,
    tokenizer=embedder.model.tokenizer,
    chunk_size=200,
    overlap=30,
)

retriever = BM25Retriever(chunks)


results = []

for item in EVALUATION_DATASET:

    relevant_chunks = resolve_relevant_chunks(
        chunks,
       item["relevant_chunks"],
    )

    if not relevant_chunks:
        print(
            f"WARNING: No matching chunk found for: "
            f"{item['query']}"
        )
        continue

    retrieved_results = retriever.retrieve(
        item["query"],
        top_k=max(K_VALUES),
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

    print()
    print(f"QUERY: {item['query']}")
    print(f"RELEVANT: {relevant_chunks}")
    print(f"RETRIEVED: {retrieved_chunks}")


print()
print("=" * 80)
print("BM25 RETRIEVAL EVALUATION")
print("=" * 80)

for k in K_VALUES:

    hit_scores = []
    recall_scores = []

    for result in results:

        hit_scores.append(
            hit_at_k(
                result["retrieved_chunks"],
                result["relevant_chunks"],
                k,
            )
        )

        recall_scores.append(
            recall_at_k(
                result["retrieved_chunks"],
                result["relevant_chunks"],
                k,
            )
        )

    hit_rate = sum(hit_scores) / len(hit_scores)
    recall = sum(recall_scores) / len(recall_scores)

    print(f"Hit@{k}:    {hit_rate:.3f}")
    print(f"Recall@{k}: {recall:.3f}")


mrr_scores = []

for result in results:

    mrr_scores.append(
        reciprocal_rank(
            result["retrieved_chunks"],
            result["relevant_chunks"],
        )
    )

mrr = sum(mrr_scores) / len(mrr_scores)

print(f"MRR:        {mrr:.3f}")

print("=" * 80)