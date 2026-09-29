"""Evidence selection utilities for claim grounding."""

import re

import numpy as np

from src.embeddings.embedder import Embedder


class EvidenceSelector:
    """Select the most relevant evidence sentences for a claim."""

    def __init__(
        self,
        embedder=None,
        similarity_threshold=0.30,
    ):
        self.embedder = embedder or Embedder()
        self.similarity_threshold = similarity_threshold

    def select(
        self,
        claim,
        evidence,
        top_k=2,
    ):
        """Select the most relevant evidence sentences for a claim."""

        if not claim or not claim.strip():
            return []

        if not evidence or not evidence.strip():
            return []

        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        sentences = self._split_sentences(evidence)

        if not sentences:
            return []

        claim_embedding = self.embedder.embed_text(
            claim
        )

        sentence_embeddings = self.embedder.embed_documents(
            [
                {"text": sentence}
                for sentence in sentences
            ]
        )

        claim_embedding = self._normalize(
            claim_embedding
        )

        sentence_embeddings = self._normalize(
            sentence_embeddings
        )

        similarities = (
            sentence_embeddings @ claim_embedding
        )

        ranked_indices = np.argsort(
            similarities
        )[::-1]

        results = []

        for index in ranked_indices:

            score = float(similarities[index])

            if score < self.similarity_threshold:
                continue

            results.append({
                "text": sentences[index],
                "score": score,
            })

            if len(results) >= top_k:
                break

        return results

    @staticmethod
    def _split_sentences(text):
        """Split text into reasonably clean sentence units."""

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if not text:
            return []

        sentences = re.split(
            r"(?<=[.!?])\s+",
            text,
        )

        return [
            sentence.strip()
            for sentence in sentences
            if sentence.strip()
        ]

    @staticmethod
    def _normalize(embeddings):
        """Normalize embeddings for cosine similarity."""

        embeddings = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        if embeddings.ndim == 1:

            norm = np.linalg.norm(
                embeddings
            )

            if norm == 0:
                return embeddings

            return embeddings / norm

        norms = np.linalg.norm(
            embeddings,
            axis=1,
            keepdims=True,
        )

        norms[norms == 0] = 1.0

        return embeddings / norms