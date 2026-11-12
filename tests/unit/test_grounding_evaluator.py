
import pytest

from src.generation.grounding_evaluator import GroundingEvaluator


class MockClaimDecomposer:
    def decompose(self, claim, context=None):
        return [claim]


class MockEvidenceSelector:
    def __init__(self, score=0.9, evidence_text=None):
        self.score = score
        self.evidence_text = evidence_text

    def select(self, claim, evidence, top_k=2):
        if not claim or not evidence:
            return []

        selected_text = self.evidence_text or evidence

        return [
            {
                "text": selected_text,
                "score": self.score,
                "semantic_score": self.score,
                "lexical_score": self.score,
            }
        ]


class MockSemanticGrounder:
    def __init__(
        self,
        label,
        probabilities=None,
        labels_by_evidence=None,
    ):
        self.label = label
        self.probabilities = probabilities
        self.labels_by_evidence = labels_by_evidence or {}

    def check_claim(self, claim, evidence):
        label = self.labels_by_evidence.get(evidence, self.label)

        default_probabilities = {
            "contradiction": 0.01,
            "entailment": 0.01,
            "neutral": 0.98,
        }
        default_probabilities[label] = 0.98

        probabilities = (
            self.probabilities
            if self.probabilities is not None
            else default_probabilities
        )

        return {
            "label": label,
            "probabilities": probabilities,
        }


SOURCE_MAP = {
    1: {
        "source": "test.pdf",
        "page": 1,
        "chunk_id": 1,
    }
}


def make_evaluator(
    *,
    nli_label="neutral",
    evidence_score=0.9,
    evidence_text=None,
    probabilities=None,
    labels_by_evidence=None,
):
    return GroundingEvaluator(
        evidence_selector=MockEvidenceSelector(
            score=evidence_score,
            evidence_text=evidence_text,
        ),
        semantic_grounder=MockSemanticGrounder(
            nli_label,
            probabilities=probabilities,
            labels_by_evidence=labels_by_evidence,
        ),
        claim_decomposer=MockClaimDecomposer(),
    )


def evaluate_claim(evaluator, claim, evidence):
    answer = f"{claim} [Source 1]"

    source_documents = [
        {
            "text": evidence,
            "metadata": {
                "page": 1,
                "chunk_id": 1,
            },
        }
    ]

    return evaluator.evaluate(
        answer=answer,
        source_map=SOURCE_MAP,
        source_documents=source_documents,
    )


def test_predecomposed_claim_is_grounded_without_second_decomposition():
    claim = "The organization prioritizes actions for managing cybersecurity risks."
    evidence = (
        "Identify, organize, and prioritize actions for managing "
        "cybersecurity risks."
    )

    evaluator = make_evaluator(nli_label="entailment")

    class RejectSecondDecomposition:
        def decompose(self, claim, context=None):
            raise AssertionError("Already-atomic claim was decomposed again.")

    evaluator.claim_decomposer = RejectSecondDecomposition()

    result = evaluator.evaluate(
        answer=f"- {claim} [Source 1]",
        source_map=SOURCE_MAP,
        source_documents=[
            {
                "text": evidence,
                "metadata": {"page": 1, "chunk_id": 1},
            }
        ],
        decompose_claims=False,
    )

    assert result[0]["status"] == "grounded"
    assert result[0]["atomic_claims"][0]["claim"] == claim
    assert result[0]["atomic_claims"][0]["status"] == "grounded"


def test_predecomposed_claim_still_fails_when_evidence_is_neutral():
    claim = "The organization operates offices in five countries."
    evaluator = make_evaluator(nli_label="neutral")

    class RejectSecondDecomposition:
        def decompose(self, claim, context=None):
            raise AssertionError("Already-atomic claim was decomposed again.")

    evaluator.claim_decomposer = RejectSecondDecomposition()

    result = evaluator.evaluate(
        answer=f"- {claim} [Source 1]",
        source_map=SOURCE_MAP,
        source_documents=[
            {
                "text": "The organization uses a cybersecurity risk framework.",
                "metadata": {"page": 1, "chunk_id": 1},
            }
        ],
        decompose_claims=False,
    )

    assert result[0]["status"] == "unsupported"


def test_supported_claim_is_grounded():
    claim = (
        "An Organizational Profile describes an organization's "
        "current cybersecurity posture."
    )
    evidence = (
        "An Organizational Profile describes an organization's "
        "current and target cybersecurity posture."
    )

    evaluator = make_evaluator(nli_label="entailment")
    result = evaluate_claim(evaluator, claim, evidence)

    assert result[0]["status"] == "grounded"
    assert result[0]["atomic_claims"][0]["status"] == "grounded"


def test_relevant_contradiction_is_detected():
    claim = "Tier 4 is Partial."
    evidence = "Tier 4 is Adaptive."

    evaluator = make_evaluator(nli_label="contradiction")
    result = evaluate_claim(evaluator, claim, evidence)

    assert result[0]["status"] == "contradicted"
    assert result[0]["atomic_claims"][0]["status"] == "contradicted"


def test_irrelevant_low_score_evidence_is_not_a_contradiction():
    claim = "Tier 4 is Adaptive."
    evidence = (
        "Tier 1 is Partial. Its cybersecurity risk strategy "
        "is managed in an ad hoc manner."
    )

    evaluator = make_evaluator(
        nli_label="contradiction",
        evidence_score=0.343,
        evidence_text=evidence,
    )
    result = evaluate_claim(evaluator, claim, evidence)

    assert result[0]["status"] == "unsupported"
    assert result[0]["atomic_claims"][0]["status"] == "unsupported"


def test_neutral_evidence_leaves_claim_unsupported():
    claim = "The organization operates offices in five countries."
    evidence = "The organization uses a cybersecurity risk framework."

    evaluator = make_evaluator(nli_label="neutral")
    result = evaluate_claim(evaluator, claim, evidence)

    assert result[0]["status"] == "unsupported"
    assert result[0]["atomic_claims"][0]["status"] == "unsupported"


def test_invalid_citation_is_unsupported():
    claim = "Tier 4 is Adaptive."
    answer = f"{claim} [Source 99]"

    evaluator = make_evaluator(nli_label="entailment")

    result = evaluator.evaluate(
        answer=answer,
        source_map=SOURCE_MAP,
        source_documents=[
            {
                "text": "Tier 4 is Adaptive.",
                "metadata": {"page": 1, "chunk_id": 1},
            }
        ],
    )

    assert result[0]["status"] == "unsupported"
    assert result[0]["atomic_claims"][0]["sources"][0]["label"] == "invalid"


def test_entailment_is_not_discarded_by_contradiction_threshold():
    """Strong entailment remains valid even below the contradiction cutoff."""
    claim = "Adequate resources are allocated."
    evidence = "Adequate resources are allocated commensurate with risk."

    evaluator = make_evaluator(
        nli_label="entailment",
        evidence_score=0.357,
    )
    result = evaluate_claim(evaluator, claim, evidence)

    assert result[0]["status"] == "grounded"
    assert result[0]["atomic_claims"][0]["status"] == "grounded"


def test_supporting_evidence_wins_over_false_contradiction():
    """A false contradiction must not override strong supporting evidence."""
    claim = "An Organizational Profile describes cybersecurity posture."

    supporting_evidence = (
        "An Organizational Profile describes current cybersecurity posture."
    )
    contradictory_evidence = (
        "Organizational Profiles are used to assess cybersecurity outcomes."
    )

    class TwoEvidenceSelector:
        def select(self, claim, evidence, top_k=2):
            return [
                {
                    "text": supporting_evidence,
                    "score": 0.60,
                    "semantic_score": 0.60,
                    "lexical_score": 0.60,
                },
                {
                    "text": contradictory_evidence,
                    "score": 0.55,
                    "semantic_score": 0.55,
                    "lexical_score": 0.55,
                },
            ]

    class MixedGrounder:
        def check_claim(self, claim, evidence):
            if evidence == supporting_evidence:
                return {
                    "label": "entailment",
                    "probabilities": {
                        "contradiction": 0.001,
                        "entailment": 0.98,
                        "neutral": 0.019,
                    },
                }

            return {
                "label": "contradiction",
                "probabilities": {
                    "contradiction": 0.99,
                    "entailment": 0.001,
                    "neutral": 0.009,
                },
            }

    evaluator = GroundingEvaluator(
        evidence_selector=TwoEvidenceSelector(),
        semantic_grounder=MixedGrounder(),
        claim_decomposer=MockClaimDecomposer(),
    )

    result = evaluate_claim(evaluator, claim, supporting_evidence)

    atomic = result[0]["atomic_claims"][0]

    assert atomic["status"] == "grounded"
    assert atomic["sources"][0]["label"] == "entailment"
    assert atomic["sources"][0]["conflict_detected"] is True


def test_unrelated_high_score_evidence_is_not_a_contradiction():
    """High similarity alone must not prove a claim is contradicted."""
    claim = "The system uses biometric authentication."
    evidence = "The system uses role-based access control."

    evaluator = make_evaluator(
        nli_label="contradiction",
        evidence_score=0.55,
        evidence_text=evidence,
    )

    result = evaluate_claim(evaluator, claim, evidence)

    assert result[0]["status"] == "unsupported"
    assert result[0]["atomic_claims"][0]["status"] == "unsupported"


def test_anaphoric_claim_context_is_forwarded_to_decomposer():
    class ContextRecordingDecomposer:
        def __init__(self):
            self.calls = []

        def decompose(self, claim, context=None):
            self.calls.append((claim, context))
            return [claim]

    decomposer = ContextRecordingDecomposer()
    evaluator = GroundingEvaluator(
        evidence_selector=MockEvidenceSelector(),
        semantic_grounder=MockSemanticGrounder("neutral"),
        claim_decomposer=decomposer,
    )
    answer = (
        "Cybersecurity supply chain risk management (C-SCRM) is a systematic process. "
        "It emphasizes coordinated supplier risk management. [Source 1]"
    )
    evaluator.evaluate(
        answer=answer,
        source_map=SOURCE_MAP,
        source_documents=[{
            "text": (
                "C-SCRM is a systematic process and coordinates supplier risk management."
            ),
            "metadata": {"page": 1, "chunk_id": 1},
        }],
    )

    assert decomposer.calls == [
        (
            "Cybersecurity supply chain risk management (C-SCRM) is a systematic process.",
            None,
        ),
        (
            "It emphasizes coordinated supplier risk management.",
            "Cybersecurity supply chain risk management (C-SCRM) is a systematic process.",
        ),
    ]

def test_exact_item_in_explicit_source_list_is_grounded_even_if_nli_is_neutral():
    """Bare answer bullets can be verified by exact membership in a cited list."""
    evidence = (
        "There are six CSF Functions: Govern, Identify, Protect, Detect, "
        "Respond, and Recover."
    )
    evaluator = make_evaluator(nli_label="neutral", evidence_text=evidence)

    for item in ("Govern", "Identify", "Protect", "Detect", "Respond", "Recover"):
        result = evaluate_claim(evaluator, item, evidence)
        atomic = result[0]["atomic_claims"][0]
        assert result[0]["status"] == "grounded", item
        assert atomic["status"] == "grounded", item
        assert atomic["sources"][0]["evidence"][0]["exact_list_item_match"] is True, item


def test_term_not_in_explicit_source_list_is_not_grounded_by_list_membership():
    evidence = (
        "There are six CSF Functions: Govern, Identify, Protect, Detect, "
        "Respond, and Recover."
    )
    evaluator = make_evaluator(nli_label="neutral", evidence_text=evidence)

    result = evaluate_claim(evaluator, "Exploit", evidence)

    assert result[0]["status"] == "unsupported"
    assert result[0]["atomic_claims"][0]["status"] == "unsupported"

def test_all_six_cited_cs_f_functions_are_grounded_as_list_items():
    evidence = (
        "There are six CSF Functions: Govern, Identify, Protect, Detect, "
        "Respond, and Recover."
    )
    items = ("Govern", "Identify", "Protect", "Detect", "Respond", "Recover")
    answer = "\n".join(f"- {item} [Source 1]" for item in items)
    evaluator = make_evaluator(nli_label="neutral", evidence_text=evidence)
    source_documents = [{
        "text": evidence,
        "metadata": {"page": 31, "chunk_id": 117},
    }]

    result = evaluator.evaluate(
        answer=answer,
        source_map=SOURCE_MAP,
        source_documents=source_documents,
    )

    assert len(result) == 6
    assert all(item["status"] == "grounded" for item in result)
