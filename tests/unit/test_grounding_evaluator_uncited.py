"""Uncited claims are reported with their own status and never verified."""

from src.generation.grounding_evaluator import GroundingEvaluator


class CountingDecomposer:
    def __init__(self):
        self.calls = []

    def decompose(self, claim, context=None):
        self.calls.append(claim)
        return [claim]


class Selector:
    def __init__(self):
        self.calls = 0

    def select(self, claim, evidence, top_k=2):
        self.calls += 1
        return [{"text": evidence, "score": 0.9}]


class EntailingGrounder:
    def check_claim(self, claim, evidence):
        return {
            "label": "entailment",
            "probabilities": {"contradiction": 0.01, "entailment": 0.98, "neutral": 0.01},
        }


SOURCE_MAP = {1: {"source": "test.pdf", "page": 1, "chunk_id": 1}}
DOCUMENTS = [{"text": "Govern sets strategy."}]


def build():
    decomposer, selector = CountingDecomposer(), Selector()
    evaluator = GroundingEvaluator(
        evidence_selector=selector,
        semantic_grounder=EntailingGrounder(),
        claim_decomposer=decomposer,
    )
    return evaluator, decomposer, selector


def test_uncited_claim_gets_uncited_status_and_is_not_verified():
    evaluator, decomposer, selector = build()
    result = evaluator.evaluate(
        "Govern sets strategy. [Source 1] Protect limits all access.",
        SOURCE_MAP,
        DOCUMENTS,
    )
    assert [item["status"] for item in result] == ["grounded", "uncited"]
    assert result[1]["atomic_claims"] == []
    assert result[1]["reason"]
    # Only the cited claim reached decomposition and evidence selection.
    assert decomposer.calls == ["Govern sets strategy."]
    assert selector.calls == 1


def test_answer_without_citations_yields_only_uncited_claims():
    evaluator, decomposer, _ = build()
    result = evaluator.evaluate("Govern sets strategy.", SOURCE_MAP, DOCUMENTS)
    assert [item["status"] for item in result] == ["uncited"]
    assert decomposer.calls == []


def test_fully_cited_answer_is_unchanged():
    evaluator, _, _ = build()
    result = evaluator.evaluate("Govern sets strategy. [Source 1]", SOURCE_MAP, DOCUMENTS)
    assert [item["status"] for item in result] == ["grounded"]
