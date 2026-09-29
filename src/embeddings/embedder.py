"""Embedding utilities for the RAG pipeline."""

from sentence_transformers import SentenceTransformer


class Embedder:
    """Generate vector embeddings for text."""

    def __init__(self, model_name="all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def embed_text(self, text):
        """Generate an embedding for a single text string."""
        return self.model.encode(text)

    def embed_documents(self, documents):
        """Generate embeddings for multiple document chunks."""
        texts = [document["text"] for document in documents]

        embeddings = self.model.encode(
            texts,
            show_progress_bar=True,
        )

        return embeddings
    