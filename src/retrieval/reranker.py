"""Cross-encoder reranking utilities."""

from sentence_transformers import CrossEncoder


class Reranker:
    """Rerank candidate documents using a cross-encoder."""

    def __init__(
        self,
        model_name="cross-encoder/ms-marco-MiniLM-L-6-v2",
    ):
        self.model = CrossEncoder(model_name)

    def rerank(self, query, documents, top_k=5):
        """Rerank documents according to query-document relevance."""

        pairs = [
            [query, document["text"]]
            for document in documents
        ]

        scores = self.model.predict(pairs)

        ranked_documents = sorted(
            zip(documents, scores),
            key=lambda item: item[1],
            reverse=True,
        )

        results = []

        for document, score in ranked_documents[:top_k]:

            results.append({
                "text": document["text"],
                "metadata": document["metadata"],
                "score": float(score),
            })

        return results