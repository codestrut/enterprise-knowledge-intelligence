
"""FAISS vector store utilities."""

import faiss
import numpy as np


class VectorStore:
    """Store and retrieve normalized document embeddings."""

    def __init__(self, dimension: int):
        if dimension <= 0:
            raise ValueError("Vector dimension must be positive.")

        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)

    def add_embeddings(self, embeddings):
        """Add embeddings without modifying the caller's array."""
        vectors = np.array(embeddings, dtype=np.float32, copy=True)

        if vectors.ndim != 2:
            raise ValueError("Embeddings must be a two-dimensional array.")

        if vectors.shape[1] != self.dimension:
            raise ValueError(
                f"Expected dimension {self.dimension}; "
                f"received {vectors.shape[1]}."
            )

        if vectors.shape[0] == 0:
            return

        if not np.isfinite(vectors).all():
            raise ValueError("Embeddings must contain finite values.")

        faiss.normalize_L2(vectors)
        self.index.add(vectors)

    def get_embeddings(self):
        """Return stored vectors in their original index order."""
        count = int(self.index.ntotal)

        if count == 0:
            return np.empty((0, self.dimension), dtype=np.float32)

        return np.asarray(
            self.index.reconstruct_n(0, count),
            dtype=np.float32,
        )

    def search(self, query_embedding, top_k=5):
        """Search using inner product over normalized vectors."""
        if top_k <= 0:
            raise ValueError("top_k must be positive.")

        if self.index.ntotal == 0:
            return (
                np.empty(0, dtype=np.float32),
                np.empty(0, dtype=np.int64),
            )

        query = np.array(
            query_embedding, dtype=np.float32, copy=True
        ).reshape(1, -1)

        if query.shape[1] != self.dimension:
            raise ValueError("Query embedding dimension mismatch.")

        faiss.normalize_L2(query)

        scores, indices = self.index.search(
            query,
            min(top_k, int(self.index.ntotal)),
        )

        return scores[0], indices[0]
