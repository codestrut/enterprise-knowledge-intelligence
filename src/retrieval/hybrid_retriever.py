
"""Hybrid retrieval using FAISS and BM25 with RRF."""

import numpy as np

from src.retrieval.retriever import Retriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.rrf import reciprocal_rank_fusion


class HybridRetriever:
    """Combine semantic and lexical retrieval using RRF."""

    def __init__(self, chunks, embeddings, embedder=None):
        self.chunks = list(chunks)

        self.vector_retriever = Retriever(
            chunks=self.chunks,
            embeddings=embeddings,
            embedder=embedder,
        )

        self.bm25_retriever = BM25Retriever(
            chunks=self.chunks,
        )

    @staticmethod
    def _get_chunk_key(chunk):
        """Return a unique identity for a chunk."""
        metadata = chunk["metadata"]

        chunk_key = metadata.get("chunk_key")

        if chunk_key is not None:
            return chunk_key

        document_id = metadata.get("document_id")

        if document_id is not None:
            return f"{document_id}:{metadata['chunk_id']}"

        return str(metadata["chunk_id"])

    def add_documents(self, chunks):
        """Add chunks to both retrieval indexes."""
        if not chunks:
            return

        self.vector_retriever.add_documents(chunks)

        try:
            self.bm25_retriever.add_documents(chunks)
        except Exception:
            self.vector_retriever.chunks = (
                self.vector_retriever.chunks[:-len(chunks)]
            )
            raise

        self.chunks.extend(chunks)

    def rebuild_excluding_document(self, document_id):
        """Build fresh indexes excluding one document.

        Existing indexes remain unchanged until the caller swaps in
        the returned replacement. Existing embeddings are reused.
        Returns None when no chunks remain.
        """
        vector_chunks = self.vector_retriever.chunks
        bm25_chunks = self.bm25_retriever.chunks

        embeddings = self.vector_retriever.get_embeddings()

        if not (
            len(self.chunks)
            == len(vector_chunks)
            == len(bm25_chunks)
            == len(embeddings)
        ):
            raise RuntimeError(
                "Hybrid retrieval indexes are inconsistent; "
                "cannot safely rebuild."
            )

        hybrid_keys = [
            self._get_chunk_key(chunk) for chunk in self.chunks
        ]
        vector_keys = [
            self._get_chunk_key(chunk) for chunk in vector_chunks
        ]
        bm25_keys = [
            self._get_chunk_key(chunk) for chunk in bm25_chunks
        ]

        if not (
            hybrid_keys == vector_keys == bm25_keys
        ):
            raise RuntimeError(
                "Retrieval index ordering differs; "
                "cannot safely rebuild."
            )

        keep_indices = [
            index
            for index, chunk in enumerate(vector_chunks)
            if chunk["metadata"].get("document_id") != document_id
        ]

        if not keep_indices:
            return None

        remaining_chunks = [
            vector_chunks[index] for index in keep_indices
        ]

        remaining_embeddings = np.asarray(
            embeddings[keep_indices],
            dtype=np.float32,
        )

        return HybridRetriever(
            chunks=remaining_chunks,
            embeddings=remaining_embeddings,
            embedder=self.vector_retriever.embedder,
        )

    def retrieve(self, query, top_k=5, candidate_k=10):
        """Retrieve documents using hybrid FAISS + BM25 search."""
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        if candidate_k <= 0:
            raise ValueError("candidate_k must be greater than zero.")

        vector_results = self.vector_retriever.retrieve(
            query,
            top_k=candidate_k,
        )

        bm25_results = self.bm25_retriever.retrieve(
            query,
            top_k=candidate_k,
        )

        vector_ranking = [
            self._get_chunk_key(result)
            for result in vector_results
        ]

        bm25_ranking = [
            self._get_chunk_key(result)
            for result in bm25_results
        ]

        fused_results = reciprocal_rank_fusion(
            [vector_ranking, bm25_ranking]
        )

        chunk_lookup = {
            self._get_chunk_key(chunk): chunk
            for chunk in self.chunks
        }

        results = []

        for chunk_key, rrf_score in fused_results[:top_k]:
            chunk = chunk_lookup[chunk_key]

            results.append({
                "text": chunk["text"],
                "metadata": chunk["metadata"],
                "score": float(rrf_score),
            })

        return results
