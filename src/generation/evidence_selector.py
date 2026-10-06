"""Evidence selection utilities for claim grounding."""

import re

import numpy as np

from src.embeddings.embedder import Embedder


class EvidenceSelector:
    """Select the most relevant evidence units for a claim."""

    def __init__(
        self,
        embedder=None,
        similarity_threshold=0.30,
        semantic_weight=0.70,
        lexical_weight=0.30,
    ):
        self.embedder = embedder or Embedder()
        self.similarity_threshold = similarity_threshold
        self.semantic_weight = semantic_weight
        self.lexical_weight = lexical_weight

    def select(self, claim, evidence, top_k=2):
        """Select the most relevant evidence units for a claim."""

        if not claim or not claim.strip():
            return []

        if not evidence or not evidence.strip():
            return []

        if top_k < 1:
            raise ValueError("top_k must be at least 1.")

        evidence_units = self._split_evidence(evidence)

        if not evidence_units:
            return []

        claim_embedding = self.embedder.embed_text(claim)

        evidence_embeddings = self.embedder.embed_documents(
            [{"text": unit} for unit in evidence_units]
        )

        claim_embedding = self._normalize(claim_embedding)
        evidence_embeddings = self._normalize(
            evidence_embeddings
        )

        semantic_scores = evidence_embeddings @ claim_embedding

        lexical_scores = np.array(
            [
                self._lexical_similarity(
                    claim,
                    evidence_unit,
                )
                for evidence_unit in evidence_units
            ],
            dtype=np.float32,
        )

        combined_scores = (
            self.semantic_weight * semantic_scores
            + self.lexical_weight * lexical_scores
        )

        ranked_indices = np.argsort(
            combined_scores
        )[::-1]

        results = []

        for index in ranked_indices:

            semantic_score = float(
                semantic_scores[index]
            )

            lexical_score = float(
                lexical_scores[index]
            )

            combined_score = float(
                combined_scores[index]
            )

            if combined_score < self.similarity_threshold:
                continue

            results.append({
                "text": evidence_units[index],
                "score": combined_score,
                "semantic_score": semantic_score,
                "lexical_score": lexical_score,
            })

            if len(results) >= top_k:
                break

        return results

    @staticmethod
    def _lexical_similarity(claim, evidence):
        """Calculate normalized lexical overlap between claim and evidence."""

        claim_tokens = set(
            EvidenceSelector._tokenize(claim)
        )

        evidence_tokens = set(
            EvidenceSelector._tokenize(evidence)
        )

        if not claim_tokens or not evidence_tokens:
            return 0.0

        overlap = claim_tokens.intersection(
            evidence_tokens
        )

        return len(overlap) / len(claim_tokens)

    @staticmethod
    def _tokenize(text):
        """Extract normalized lexical tokens."""

        return re.findall(
            r"\b[a-zA-Z0-9]+(?:[._-][a-zA-Z0-9]+)*\b",
            text.lower(),
        )

    @staticmethod
    def _split_evidence(text):
        """Split evidence into semantically useful units."""

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        if not text:
            return []

        # First split structured NIST CSF outcomes.
        #
        # Example:
        # GV.RR-01: ...
        # GV.RR-02: ...
        # GV.RR-03: ...
        #
        # Each outcome becomes its own evidence unit.
        outcome_pattern = re.compile(
            r"(?=\b[A-Z]{2}\.[A-Z]{2}-\d{2}\s*:)"
        )

        outcome_units = [
            unit.strip()
            for unit in outcome_pattern.split(text)
            if unit.strip()
        ]

        # If NIST-style outcomes were found, process each
        # outcome independently.
        if len(outcome_units) > 1:
            return EvidenceSelector._split_structured_units(
                outcome_units
            )

        # Fall back to sentence-based splitting.
        sentences = re.split(
            r"(?<=[.!?])\s+",
            text,
        )

        units = []
        index = 0

        while index < len(sentences):

            current = sentences[index].strip()

            if not current:
                index += 1
                continue

            if (
                re.search(r":\s*\d+\.$", current)
                and index + 1 < len(sentences)
            ):
                current = (
                    current
                    + " "
                    + sentences[index + 1].strip()
                )

                index += 2
                units.append(current)

                continue

            if (
                re.fullmatch(r"\d+\.", current)
                and index + 1 < len(sentences)
            ):
                current = (
                    current
                    + " "
                    + sentences[index + 1].strip()
                )

                index += 2
                units.append(current)

                continue

            units.append(current)
            index += 1

        return units

    @staticmethod
    def _split_structured_units(units):
        """Split NIST outcome units while preserving full content."""

        results = []

        for unit in units:

            unit = unit.strip()

            if not unit:
                continue

            results.append(unit)

        return results

    @staticmethod
    def _normalize(embeddings):
        embeddings = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        if embeddings.ndim == 1:
            norm = np.linalg.norm(embeddings)

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