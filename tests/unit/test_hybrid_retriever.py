"""Test hybrid FAISS + BM25 retrieval."""

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.retrieval.hybrid_retriever import HybridRetriever


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


# Load document
documents = load_pdf(PDF_PATH)

# Create chunks
chunks = chunk_documents(documents)

# Generate embeddings
embedder = Embedder()
embeddings = embedder.embed_documents(chunks)

# Create hybrid retriever
retriever = HybridRetriever(
    chunks=chunks,
    embeddings=embeddings,
)


queries = [
    "What is GV.RR-01?",
    "What is an Organizational Profile?",
    "What is cybersecurity supply chain risk management?",
    "How are access permissions and authorizations managed?",
]


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
        print(f"RRF Score: {result['score']:.6f}")
        print(
            f"Chunk ID: "
            f"{result['metadata']['chunk_id']}"
        )
        print(
            f"Page: "
            f"{result['metadata']['page']}"
        )
        print(result["text"][:500])