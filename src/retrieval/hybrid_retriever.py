"""Hybrid retrieval using FAISS and BM25 with RRF."""

from src.retrieval.retriever import Retriever
from src.retrieval.bm25_retriever import BM25Retriever
from src.retrieval.rrf import reciprocal_rank_fusion


class HybridRetriever:
    """Combine semantic and lexical retrieval using RRF."""

    def __init__(self, chunks, embeddings, embedder=None):
        self.chunks = chunks

        self.vector_retriever = Retriever(
            chunks=chunks,
            embeddings=embeddings,
            embedder=embedder,
        )

        self.bm25_retriever = BM25Retriever(
            chunks=chunks,
        )

    def retrieve(self, query, top_k=5, candidate_k=10):
        """Retrieve documents using hybrid FAISS + BM25 search."""

        vector_results = self.vector_retriever.retrieve(
            query,
            top_k=candidate_k,
        )

        bm25_results = self.bm25_retriever.retrieve(
            query,
            top_k=candidate_k,
        )

        vector_ranking = [
            result["metadata"]["chunk_id"]
            for result in vector_results
        ]

        bm25_ranking = [
            result["metadata"]["chunk_id"]
            for result in bm25_results
        ]

        fused_results = reciprocal_rank_fusion(
            [
                vector_ranking,
                bm25_ranking,
            ]
        )

        chunk_lookup = {
            chunk["metadata"]["chunk_id"]: chunk
            for chunk in self.chunks
        }

        results = []

        for chunk_id, rrf_score in fused_results[:top_k]:

            chunk = chunk_lookup[chunk_id]

            results.append({
                "text": chunk["text"],
                "metadata": chunk["metadata"],
                "score": float(rrf_score),
            })

        return results