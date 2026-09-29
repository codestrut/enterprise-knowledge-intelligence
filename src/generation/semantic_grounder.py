"""Semantic grounding utilities for the RAG pipeline."""

import numpy as np

from sentence_transformers import CrossEncoder


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
    ):
        self.model = CrossEncoder(model_name)

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

        return {
            "label": self.LABELS[predicted_index],
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