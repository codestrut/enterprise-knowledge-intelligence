"""Document retrieval utilities."""

from src.embeddings.embedder import Embedder
from src.retrieval.vector_store import VectorStore


class Retriever:
    """Retrieve relevant document chunks using vector similarity."""

    def __init__(self, chunks, embeddings, embedder=None):
        self.chunks = chunks
        self.embedder = embedder or Embedder()

        self.vector_store = VectorStore(
            dimension=embeddings.shape[1]
        )

        self.vector_store.add_embeddings(embeddings)

    def retrieve(self, query, top_k=5):
        """Retrieve the top-k most relevant chunks."""

        query_embedding = self.embedder.embed_text(query)

        scores, indices = self.vector_store.search(
            query_embedding,
            top_k=top_k,
        )

        results = []

        for score, index in zip(scores, indices):
            results.append({
                "text": self.chunks[index]["text"],
                "metadata": self.chunks[index]["metadata"],
                "score": float(score),
            })

        return results