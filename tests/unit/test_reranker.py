"""Test the cross-encoder reranker."""

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents
from src.retrieval.reranker import Reranker


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


# Load document
documents = load_pdf(PDF_PATH)

# Create chunks
chunks = chunk_documents(documents)

# Load reranker
reranker = Reranker()


query = "What is GV.RR-01?"

# Select a few candidates deliberately.
candidate_ids = [29, 30, 28, 25, 6]

candidates = [
    chunks[chunk_id]
    for chunk_id in candidate_ids
]


# Rerank candidates
results = reranker.rerank(
    query,
    candidates,
    top_k=5,
)


print("\n" + "=" * 80)
print(f"QUERY: {query}")
print("=" * 80)

for rank, result in enumerate(results, start=1):

    print(f"\nRank: {rank}")
    print(f"Reranker Score: {result['score']:.4f}")
    print(
        f"Chunk ID: "
        f"{result['metadata']['chunk_id']}"
    )
    print(
        f"Page: "
        f"{result['metadata']['page']}"
    )
    print(result["text"][:500])