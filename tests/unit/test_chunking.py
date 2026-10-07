"""Tests for the document chunking module."""

from sentence_transformers import SentenceTransformer

from src.chunking.text_chunker import chunk_documents
from src.ingestion.pdf_loader import load_pdf


PDF_PATH = "data/raw/nist_csf_2.0.pdf"


def test_chunk_documents():
    """Chunk the NIST document using the embedding model tokenizer."""

    documents = load_pdf(PDF_PATH)

    embedder = SentenceTransformer("all-MiniLM-L6-v2")

    chunks = chunk_documents(
        documents,
        tokenizer=embedder.tokenizer,
        chunk_size=200,
        overlap=30,
    )

    assert len(documents) > 0
    assert len(chunks) > 0

    token_counts = [
        len(
            embedder.tokenizer.encode(
                chunk["text"],
                add_special_tokens=False,
            )
        )
        for chunk in chunks
    ]

    assert max(token_counts) <= 200
    assert all(
        chunk["text"].strip()
        for chunk in chunks
    )

    assert all(
        "chunk_id" in chunk["metadata"]
        for chunk in chunks
    )