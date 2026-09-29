"""Hybrid retrieval followed by cross-encoder reranking."""

from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import Reranker


class RerankedRetriever:
    """Retrieve candidates with hybrid search, then rerank them."""

    def __init__(self, chunks, embeddings, embedder=None):
        self.hybrid_retriever = HybridRetriever(
            chunks=chunks,
            embeddings=embeddings,
            embedder=embedder,
        )

        self.reranker = Reranker()

    def retrieve(
        self,
        query,
        top_k=5,
        candidate_k=20,
    ):
        """Retrieve hybrid candidates and rerank them."""

        candidates = self.hybrid_retriever.retrieve(
            query,
            top_k=candidate_k,
            candidate_k=candidate_k,
        )

        results = self.reranker.rerank(
            query,
            candidates,
            top_k=top_k,
        )

        return results