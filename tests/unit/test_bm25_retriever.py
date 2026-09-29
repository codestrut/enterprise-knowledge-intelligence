"""Test BM25 lexical retrieval."""

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents
from src.retrieval.bm25_retriever import BM25Retriever


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


# Load the document
documents = load_pdf(PDF_PATH)

# Create chunks
chunks = chunk_documents(documents)

# Create BM25 retriever
retriever = BM25Retriever(chunks)


# Test queries
queries = [
    "What is GV.RR-01?",
    "What is an Organizational Profile?",
    "What is cybersecurity supply chain risk management?",
]


# Retrieve results
for query in queries:

    results = retriever.retrieve(
        query,
        top_k=5,
    )

    print("\n" + "=" * 80)
    print(f"QUERY: {query}")
    print("=" * 80)

    for rank, result in enumerate(results, start=1):

        print(f"\nRank: {rank}")
        print(f"Score: {result['score']:.4f}")
        print(
            f"Chunk ID: "
            f"{result['metadata']['chunk_id']}"
        )
        print(
            f"Page: "
            f"{result['metadata']['page']}"
        )
        print(result["text"][:500])