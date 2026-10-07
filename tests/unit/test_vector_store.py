"""Tests for the FAISS vector store."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.vector_store import VectorStore


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_vector_store_search():
    """Verify FAISS vector search returns ranked results."""

    documents = load_pdf(PDF_PATH)

    embedder = Embedder()

    chunks = chunk_documents(
        documents,
        tokenizer=embedder.model.tokenizer,
        chunk_size=200,
        overlap=30,
    )

    embeddings = embedder.embed_documents(chunks)

    vector_store = VectorStore(
        dimension=embeddings.shape[1]
    )

    vector_store.add_embeddings(embeddings)

    query = "How does NIST manage cybersecurity risk?"

    query_embedding = embedder.embed_text(query)

    scores, indices = vector_store.search(
        query_embedding,
        top_k=3,
    )

    assert len(scores) == 3
    assert len(indices) == 3

    assert all(
        0 <= index < len(chunks)
        for index in indices
    )

    assert all(
        scores[index] <= scores[index - 1]
        for index in range(1, len(scores))
    )