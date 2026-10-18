"""Hybrid retrieval followed by cross-encoder reranking."""

from src.retrieval.hybrid_retriever import HybridRetriever
from src.retrieval.reranker import Reranker


class RerankedRetriever:
    """Retrieve candidates with hybrid search, then rerank them."""

    def __init__(self, chunks, embeddings, embedder=None, reranker=None):
        self.hybrid_retriever = HybridRetriever(
            chunks=chunks,
            embeddings=embeddings,
            embedder=embedder,
        )

        self.reranker = reranker if reranker is not None else Reranker()

    def add_documents(self, chunks):
        """Add documents to the underlying hybrid retrieval indexes."""

        self.hybrid_retriever.add_documents(chunks)

    def retrieve(
        self,
        query,
        top_k=5,
        candidate_k=20,
    ):
        """Retrieve hybrid candidates and rerank them."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        if candidate_k <= 0:
            raise ValueError("candidate_k must be greater than zero.")

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
