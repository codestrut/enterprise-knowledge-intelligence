"""Document retrieval utilities."""

import numpy as np

from src.embeddings.embedder import Embedder
from src.retrieval.vector_store import VectorStore


class Retriever:
    """Retrieve document chunks using vector similarity."""

    def __init__(self, chunks, embeddings, embedder=None):
        self.chunks = list(chunks)
        self.embedder = embedder or Embedder()

        embeddings = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        if embeddings.ndim != 2:
            raise ValueError(
                "Embeddings must be a two-dimensional array."
            )

        if len(self.chunks) != len(embeddings):
            raise ValueError(
                "The number of chunks must match the number of embeddings."
            )

        if len(embeddings) == 0:
            raise ValueError(
                "At least one embedding is required to initialize Retriever."
            )

        self.vector_store = VectorStore(
            dimension=embeddings.shape[1]
        )

        self.vector_store.add_embeddings(embeddings)

    def add_documents(self, chunks):
        """Embed and index new chunks without rebuilding the FAISS index."""

        if not chunks:
            return

        new_embeddings = self.embedder.embed_documents(chunks)

        new_embeddings = np.asarray(
            new_embeddings,
            dtype=np.float32,
        )

        if new_embeddings.ndim != 2:
            raise ValueError(
                "New embeddings must be a two-dimensional array."
            )

        if len(chunks) != len(new_embeddings):
            raise ValueError(
                "The number of new chunks must match the number of embeddings."
            )

        if new_embeddings.shape[1] != self.vector_store.dimension:
            raise ValueError(
                "New embeddings must match the existing vector dimension."
            )

        # Add to FAISS first so the chunk list remains unchanged
        # if vector insertion fails.
        self.vector_store.add_embeddings(new_embeddings)
        self.chunks.extend(chunks)



    def get_embeddings(self):
        """Return embeddings aligned with self.chunks."""
        embeddings = self.vector_store.get_embeddings()

        if len(embeddings) != len(self.chunks):
            raise RuntimeError(
                "Vector index and chunk collection are inconsistent."
            )

        return embeddings


    def retrieve(self, query, top_k=5):
        """Retrieve the top-k most relevant document chunks."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        if not self.chunks:
            return []

        query_embedding = self.embedder.embed_text(query)

        search_k = min(
            top_k,
            self.vector_store.index.ntotal,
        )

        scores, indices = self.vector_store.search(
            query_embedding,
            top_k=search_k,
        )

        results = []

        for score, index in zip(scores, indices):
            if index < 0 or index >= len(self.chunks):
                continue

            chunk = self.chunks[int(index)]

            results.append({
                "text": chunk["text"],
                "metadata": chunk["metadata"],
                "score": float(score),
            })

        return results
