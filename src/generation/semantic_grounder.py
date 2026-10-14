"""Semantic grounding utilities for the RAG pipeline."""

import numpy as np

from sentence_transformers import CrossEncoder

from src.generation.grounding_relation_guard import apply_contradiction_guard
from src.generation.lexical_support_guard import apply_near_extractive_support_guard


class SemanticGrounder:
    """Evaluate whether evidence supports a claim."""

    LABELS = [
        "contradiction",
        "entailment",
        "neutral",
    ]

    def __init__(
        self,
        model_name="cross-encoder/nli-deberta-v3-base",
        max_length=256,
        require_conflict_cue=True,
    ):
        self.model_name = model_name
        self.max_length = max_length
        # When True, a raw NLI contradiction is kept only if the pair shows a
        # detectable conflict cue (see grounding_relation_guard).
        self.require_conflict_cue = require_conflict_cue
        # Explicit max_length prevents token-limit warnings/indexing failures.
        # The model/tokenizer performs bounded truncation if a pair is too long.
        self.model = CrossEncoder(model_name, max_length=max_length)

    def check_claim(self, claim, evidence):
        """Classify the relationship between evidence and claim."""

        logits = self.model.predict(
            [
                [evidence, claim],
            ]
        )[0]

        probabilities = self._softmax(logits)

        predicted_index = int(
            np.argmax(probabilities)
        )
        raw_label = self.LABELS[predicted_index]
        label, relation_guard = apply_contradiction_guard(
            claim=claim,
            evidence=evidence,
            raw_label=raw_label,
            require_conflict_cue=self.require_conflict_cue,
        )
        label, support_guard = apply_near_extractive_support_guard(
            claim=claim,
            evidence=evidence,
            raw_label=raw_label,
            current_label=label,
        )

        return {
            # label is the effective relation after conservative guards.
            "label": label,
            # Keep model output visible for auditing and benchmark metrics.
            "raw_label": raw_label,
            "relation_guard": relation_guard,
            "support_guard": support_guard,
            "probabilities": {
                label: float(probability)
                for label, probability in zip(
                    self.LABELS,
                    probabilities,
                )
            },
        }

    @staticmethod
    def _softmax(logits):
        """Convert logits into probabilities."""

        logits = np.asarray(
            logits,
            dtype=np.float64,
        )

        exponentials = np.exp(
            logits - np.max(logits)
        )

        return exponentials / exponentials.sum()