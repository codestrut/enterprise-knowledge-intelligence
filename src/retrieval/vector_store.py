"""FAISS vector store utilities."""

import faiss
import numpy as np


class VectorStore:
    """FAISS vector store using cosine similarity."""

    def __init__(self, dimension):
        self.dimension = dimension

        # Inner product on normalized vectors = cosine similarity.
        self.index = faiss.IndexFlatIP(dimension)

    def add_embeddings(self, embeddings):
        """Add normalized embeddings to the FAISS index."""

        embeddings = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        faiss.normalize_L2(embeddings)

        self.index.add(embeddings)

    def search(self, query_embedding, top_k=5):
        """Search for the most similar vectors."""

        query_embedding = np.asarray(
            [query_embedding],
            dtype=np.float32,
        )

        faiss.normalize_L2(query_embedding)

        scores, indices = self.index.search(
            query_embedding,
            top_k,
        )

        return scores[0], indices[0]