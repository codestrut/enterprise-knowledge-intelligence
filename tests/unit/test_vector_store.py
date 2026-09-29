"""Test FAISS vector retrieval."""

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.retrieval.vector_store import VectorStore


pdf_path = "data/raw/nist_csf_2.0.pdf"

# Load documents
documents = load_pdf(pdf_path)

# Chunk documents
chunks = chunk_documents(documents)

# Embed chunks
embedder = Embedder()

embeddings = embedder.embed_documents(chunks)

# Build vector store
vector_store = VectorStore(
    dimension=embeddings.shape[1]
)

vector_store.add_embeddings(embeddings)

# Query
query = "How does NIST manage cybersecurity risk?"

query_embedding = embedder.embed_text(query)

scores, indices = vector_store.search(
    query_embedding,
    top_k=3
)

print("\nTop Results:\n")

for rank, index in enumerate(indices, start=1):
    print(f"Rank: {rank}")
    print(f"Chunk ID: {index}")
    print(f"Similarity: {distances[rank-1]:.4f}")
    print("-" * 50)
    print(chunks[index]["text"][:500])
    print("\n")