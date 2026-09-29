"""BM25 lexical retrieval utilities."""

import re

from rank_bm25 import BM25Okapi


class BM25Retriever:
    """Retrieve document chunks using BM25 lexical similarity."""

    def __init__(self, chunks):
        self.chunks = chunks

        # Tokenize every chunk for BM25 indexing.
        self.tokenized_chunks = [
            self._tokenize(chunk["text"])
            for chunk in chunks
        ]

        # Build the BM25 index.
        self.bm25 = BM25Okapi(self.tokenized_chunks)

    @staticmethod
    def _tokenize(text):
        """Convert text into normalized word/term tokens."""

        return re.findall(
            r"\b\w+\b",
            text.lower(),
        )

    def retrieve(self, query, top_k=5):
        """Retrieve the top-k chunks for a query."""

        query_tokens = self._tokenize(query)

        scores = self.bm25.get_scores(query_tokens)

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )[:top_k]

        results = []

        for index in ranked_indices:
            results.append({
                "text": self.chunks[index]["text"],
                "metadata": self.chunks[index]["metadata"],
                "score": float(scores[index]),
            })

        return results