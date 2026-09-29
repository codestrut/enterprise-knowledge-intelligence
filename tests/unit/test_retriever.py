"""Test the document retriever."""

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.retrieval.retriever import Retriever


pdf_path = "data/raw/nist_csf_2.0.pdf"

# 1. Load documents
documents = load_pdf(pdf_path)

# 2. Create chunks
chunks = chunk_documents(documents)

# 3. Generate document embeddings
embedder = Embedder()
embeddings = embedder.embed_documents(chunks)

# 4. Create retriever
retriever = Retriever(
    chunks=chunks,
    embeddings=embeddings,
)

# 5. Search
queries = [
    "What is cybersecurity risk management?",
    "What does NIST say about cybersecurity roles and responsibilities?",
    "What is an Organizational Profile?",
    "How should an organization prioritize its cybersecurity risks?",
]


for query in queries:
    print("\n")
    print("#" * 80)
    print(f"QUERY: {query}")
    print("#" * 80)

    results = retriever.retrieve(
        query,
        top_k=3,
    )

    for rank, result in enumerate(results, start=1):
        print(f"\nRank: {rank}")
        print(f"Score: {result['score']:.4f}")
        print(f"Chunk ID: {result['metadata']['chunk_id']}")
        print(f"Page: {result['metadata']['page']}")
        print(result["text"][:500])

results = retriever.retrieve(
    query,
    top_k=5,
)

# 6. Display results
print("\nTop Retrieved Chunks:\n")

for rank, result in enumerate(results, start=1):
    print(f"{'=' * 70}")
    print(f"Rank: {rank}")
    print(f"Score: {result['score']:.4f}")
    print(f"Chunk ID: {result['metadata']['chunk_id']}")
    print(f"Page: {result['metadata']['page']}")
    print(f"{'=' * 70}")
    print(result["text"][:700])
    print()
    