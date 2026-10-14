"""BM25 lexical retrieval utilities."""

import re

import numpy as np
from rank_bm25 import BM25Okapi


class BM25Retriever:
    """Retrieve document chunks using BM25 lexical similarity."""

    def __init__(self, chunks):
        self.chunks = list(chunks)
        self._build_index()

    @staticmethod
    def _tokenize(text):
        """Normalize text into lowercase word tokens."""
        return re.findall(r"\b\w+\b", text.lower())

    def _build_index(self):
        """Build the BM25 index from the current chunk collection."""

        self.tokenized_chunks = [
            self._tokenize(chunk["text"])
            for chunk in self.chunks
        ]

        if not self.tokenized_chunks:
            self.bm25 = None
            return

        self.bm25 = BM25Okapi(self.tokenized_chunks)

        # Standard BM25 can assign zero or negative IDF to terms
        # common in a small corpus. Apply a positive floor so that
        # matching terms can still distinguish relevant documents.
        self.bm25.idf = {
            term: max(float(idf), 0.25)
            for term, idf in self.bm25.idf.items()
        }

        self.bm25.average_idf = max(
            float(self.bm25.average_idf),
            0.25,
        )

    def add_documents(self, chunks):
        """Add chunks and rebuild the lexical index."""

        if not chunks:
            return

        self.chunks.extend(chunks)
        self._build_index()

    def retrieve(self, query, top_k=5):
        """Retrieve the top-k chunks ranked by BM25 score."""

        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        if self.bm25 is None:
            return []

        query_tokens = self._tokenize(query)

        if not query_tokens:
            return []

        scores = self.bm25.get_scores(query_tokens)

        ranked_indices = sorted(
            range(len(scores)),
            key=lambda index: scores[index],
            reverse=True,
        )[:top_k]

        return [
            {
                "text": self.chunks[index]["text"],
                "metadata": self.chunks[index]["metadata"],
                "score": float(scores[index]),
            }
            for index in ranked_indices
        ]