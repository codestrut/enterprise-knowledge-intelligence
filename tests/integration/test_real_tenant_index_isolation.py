import numpy as np

from src.retrieval.reranked_retriever import RerankedRetriever


class FakeEmbedder:
    """Deterministic embeddings for synthetic tenant canaries."""

    def embed_text(self, text):
        text = text.lower()
        if "alpha" in text:
            return np.array([1.0, 0.0], dtype=np.float32)
        if "beta" in text:
            return np.array([0.0, 1.0], dtype=np.float32)
        return np.array([0.5, 0.5], dtype=np.float32)


class FakeReranker:
    """Keep the real hybrid results without external model calls."""

    def rerank(self, query, documents, top_k=5):
        return documents[:top_k]


def make_chunk(document_id, text, organisation_id):
    return {
        "text": text,
        "metadata": {
            "document_id": document_id,
            "chunk_id": 0,
            "chunk_key": f"{document_id}:0",
            "organisation_id": organisation_id,
        },
    }


def make_workspace(chunks, embeddings, embedder):
    return RerankedRetriever(
        chunks=chunks,
        embeddings=embeddings,
        embedder=embedder,
        reranker=FakeReranker(),
    )


def test_real_faiss_and_bm25_indexes_are_separate_by_workspace():
    embedder = FakeEmbedder()

    alpha_chunk = make_chunk(
        "alpha-doc",
        "alpha canary alpha confidential project",
        "alpha-org",
    )
    beta_chunk = make_chunk(
        "beta-doc",
        "beta canary beta confidential project",
        "beta-org",
    )

    alpha = make_workspace(
        [alpha_chunk],
        np.array([[1.0, 0.0]], dtype=np.float32),
        embedder,
    )
    beta = make_workspace(
        [beta_chunk],
        np.array([[0.0, 1.0]], dtype=np.float32),
        embedder,
    )

    alpha_results = alpha.retrieve("alpha canary", top_k=5)
    beta_results = beta.retrieve("beta canary", top_k=5)

    alpha_ids = {
        result["metadata"]["document_id"] for result in alpha_results
    }
    beta_ids = {
        result["metadata"]["document_id"] for result in beta_results
    }

    assert alpha_ids == {"alpha-doc"}
    assert beta_ids == {"beta-doc"}
    assert "beta-doc" not in alpha_ids
    assert "alpha-doc" not in beta_ids

    assert alpha.hybrid_retriever.vector_retriever.vector_store.index.ntotal == 1
    assert beta.hybrid_retriever.vector_retriever.vector_store.index.ntotal == 1

    assert alpha.hybrid_retriever.bm25_retriever.chunks == [alpha_chunk]
    assert beta.hybrid_retriever.bm25_retriever.chunks == [beta_chunk]
