from src.generation.grounding_evaluator import GroundingEvaluator


class MockClaimDecomposer:
    def decompose(self, claim, context=None):
        return [claim]


class MockEvidenceSelector:
    def select(self, claim, evidence, top_k=2):
        return [{"text": evidence, "score": 0.95}]


class MockSemanticGrounder:
    def __init__(self, label, support_guard_applied=False):
        self.label = label
        self.support_guard_applied = support_guard_applied

    def check_claim(self, claim, evidence):
        return {
            "label": self.label,
            "raw_label": "neutral" if self.support_guard_applied else self.label,
            "relation_guard": {"applied": False, "reason": "not needed"},
            "support_guard": {
                "applied": self.support_guard_applied,
                "reason": "near-extractive support" if self.support_guard_applied else "coverage low",
            },
            "probabilities": {
                "contradiction": 0.01,
                "entailment": 0.02 if self.support_guard_applied else (0.98 if self.label == "entailment" else 0.01),
                "neutral": 0.97 if self.support_guard_applied else (0.01 if self.label != "neutral" else 0.98),
            },
        }


def evaluate(label, support_guard_applied):
    evidence = "Prioritize actions for managing cybersecurity risks that align with the organization's mission."
    claim = "The actions align with the organization's mission."
    evaluator = GroundingEvaluator(
        evidence_selector=MockEvidenceSelector(),
        semantic_grounder=MockSemanticGrounder(label, support_guard_applied),
        claim_decomposer=MockClaimDecomposer(),
    )
    return evaluator.evaluate(
        answer=f"{claim} [Source 1]",
        source_map={1: {"source": "test.md", "page": 1}},
        source_documents=[{"text": evidence, "metadata": {"page": 1}}],
    )


def test_near_extractive_support_guard_is_respected_by_evaluator():
    result = evaluate(label="entailment", support_guard_applied=True)
    assert result[0]["status"] == "grounded"
    atomic = result[0]["atomic_claims"][0]
    assert atomic["status"] == "grounded"
    assert atomic["sources"][0]["evidence"][0]["raw_label"] == "neutral"
    assert atomic["sources"][0]["evidence"][0]["support_guard"]["applied"] is True


def test_neutral_without_support_guard_remains_unsupported():
    result = evaluate(label="neutral", support_guard_applied=False)
    assert result[0]["status"] == "unsupported"


def test_model_entailment_still_requires_configured_confidence():
    # A test double with low entailment confidence but no applied support guard
    # must not become grounded merely because the nominal label is entailment.
    class LowConfidenceGrounder:
        def check_claim(self, claim, evidence):
            return {
                "label": "entailment",
                "raw_label": "entailment",
                "relation_guard": {"applied": False},
                "support_guard": {"applied": False},
                "probabilities": {
                    "contradiction": 0.01,
                    "entailment": 0.02,
                    "neutral": 0.97,
                },
            }

    evidence = "A sufficiently relevant passage about a process and its controls."
    evaluator = GroundingEvaluator(
        evidence_selector=MockEvidenceSelector(),
        semantic_grounder=LowConfidenceGrounder(),
        claim_decomposer=MockClaimDecomposer(),
    )
    result = evaluator.evaluate(
        answer="A process has controls [Source 1]",
        source_map={1: {"source": "test.md", "page": 1}},
        source_documents=[{"text": evidence, "metadata": {"page": 1}}],
    )
    assert result[0]["status"] == "unsupported"
