"""Fast regressions for unanswered questions and conflicting cited sources.

These tests use doubles, so they do not call an external LLM or download models.
They check EKIP's control flow and the source-conflict classification rule.
"""
from types import SimpleNamespace

from src.generation.grounding_evaluator import GroundingEvaluator
from src.generation.answer_repair import ABSTENTION_TEXT, build_repair_prompt
from src.rag_pipeline import RAGPipeline


class _FailIfCalled:
    def __init__(self):
        self.calls = 0

    def generate(self, _prompt):
        self.calls += 1
        raise AssertionError("LLM must not be called when evidence is insufficient")


class _FakeHybrid:
    def __init__(self, documents):
        self.chunks = list(documents)
        self.vector_retriever = SimpleNamespace(
            vector_store=SimpleNamespace(index=SimpleNamespace(ntotal=len(documents))),
            chunks=list(documents),
        )
        self.bm25_retriever = SimpleNamespace(chunks=list(documents))
        self._documents = list(documents)

    def retrieve(self, _question, top_k=5, candidate_k=10):
        return self._documents[:top_k]


class _FakeRetriever:
    def __init__(self, documents):
        self.hybrid_retriever = _FakeHybrid(documents)
        self._documents = list(documents)

    def retrieve(self, _question, top_k=5):
        return self._documents[:top_k]


def _pipeline_with_documents(documents, llm=None, grounding_evaluator=None):
    pipeline = RAGPipeline.__new__(RAGPipeline)
    pipeline.knowledge_base = None
    pipeline.retrieval_backend = "custom"
    pipeline.chunks = list(documents)
    pipeline.retriever = _FakeRetriever(documents)
    pipeline.llm = llm or _FailIfCalled()
    pipeline.grounding_evaluator = grounding_evaluator or _FailIfCalled()
    return pipeline


def test_unanswerable_query_with_no_retrieved_evidence_abstains_before_generation():
    pipeline = _pipeline_with_documents([])

    result = pipeline.query("What is the default password for a Cisco firewall?")

    assert result["refused"] is True
    assert result["answer"] == ABSTENTION_TEXT
    assert result["evidence"]["sufficient"] is False
    assert result["citations"] == []
    assert pipeline.llm.calls == 0
    assert pipeline.grounding_evaluator.calls == 0


def test_low_relevance_retrieval_for_unanswerable_query_abstains_before_generation():
    irrelevant = {
        "text": "The NIST CSF describes outcomes for managing cybersecurity risk.",
        "score": 1.2,
        "metadata": {"source": "nist.pdf", "page": 1, "chunk_id": 1},
    }
    pipeline = _pipeline_with_documents([irrelevant])

    result = pipeline.query("Which encryption algorithm does NIST CSF 2.0 require?")

    assert result["refused"] is True
    assert result["evidence"]["sufficient"] is False
    assert result["answer"] == ABSTENTION_TEXT
    assert pipeline.llm.calls == 0


class _IdentityDecomposer:
    def decompose(self, claim, context=None):
        return [claim]


class _EvidenceSelector:
    def select(self, claim, evidence, top_k=2):
        return [{"text": evidence, "score": 0.95}]


class _KnownConflictGrounder:
    """Deterministic stand-in for a labelled pairwise NLI response."""

    def check_claim(self, claim, evidence):
        if "30 calendar days" in evidence:
            label = "entailment"
        else:
            label = "contradiction"
        probabilities = {"entailment": 0.01, "contradiction": 0.01, "neutral": 0.98}
        probabilities[label] = 0.98
        return {
            "label": label,
            "raw_label": label,
            "probabilities": probabilities,
            "relation_guard": {"applied": False},
            "support_guard": {"applied": False},
        }


def test_conflicting_cited_sources_are_not_silently_marked_grounded():
    source_one = "Expense claims must be submitted within 30 calendar days of the purchase."
    source_two = "Expense claims must be submitted within 10 calendar days of the purchase."
    evaluator = GroundingEvaluator(
        evidence_selector=_EvidenceSelector(),
        semantic_grounder=_KnownConflictGrounder(),
        claim_decomposer=_IdentityDecomposer(),
    )

    result = evaluator.evaluate(
        answer=(
            "Expense claims must be submitted within 30 calendar days of the purchase. "
            "[Source 1][Source 2]"
        ),
        source_map={
            1: {"source": "policy-a.pdf", "page": 1},
            2: {"source": "policy-b.pdf", "page": 2},
        },
        source_documents=[
            {"text": source_one, "metadata": {"page": 1}},
            {"text": source_two, "metadata": {"page": 2}},
        ],
    )

    assert result[0]["atomic_claims"][0]["sources"][0]["label"] == "entailment"
    assert result[0]["atomic_claims"][0]["sources"][1]["label"] == "contradiction"
    assert result[0]["status"] == "contradicted"


def test_repair_prompt_requires_source_by_source_conflict_handling():
    prompt = build_repair_prompt(
        query="What is the expense-claim deadline?",
        context=(
            "[Source 1] Expense claims are due within 30 calendar days.\n"
            "[Source 2] Expense claims are due within 10 calendar days."
        ),
        draft_answer="Expense claims are due within 30 calendar days. [Source 1][Source 2]",
        issues=[{"claim": "Expense claims are due within 30 days", "status": "contradicted"}],
    )

    assert "do not select a value arbitrarily" in prompt.lower()
    assert "report each source's claim separately" in prompt.lower()
    assert ABSTENTION_TEXT in prompt


class _SequenceLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if not self.outputs:
            raise AssertionError("Unexpected additional generation call")
        return self.outputs.pop(0)


class _ConflictRepairGrounding:
    def __init__(self):
        self.calls = 0

    def evaluate(self, answer, source_map, source_documents):
        self.calls += 1
        if self.calls == 1:
            return [{
                "claim": "Expense claims are due within 30 days.",
                "status": "contradicted",
                "atomic_claims": [],
            }]
        return [
            {
                "claim": "Source 1 states a 30-day deadline.",
                "status": "grounded",
                "atomic_claims": [],
            },
            {
                "claim": "Source 2 states a 10-day deadline.",
                "status": "grounded",
                "atomic_claims": [],
            },
        ]


def test_conflicting_source_answer_is_repaired_as_source_specific_statements():
    docs = [
        {
            "text": "Expense claims must be submitted within 30 calendar days of purchase.",
            "score": 4.7,
            "metadata": {"source": "policy-a.pdf", "page": 1, "chunk_id": 11},
        },
        {
            "text": "Expense claims must be submitted within 10 calendar days of purchase.",
            "score": 4.6,
            "metadata": {"source": "policy-b.pdf", "page": 2, "chunk_id": 22},
        },
    ]
    llm = _SequenceLLM([
        "Expense claims must be submitted within 30 calendar days of purchase. [Source 1][Source 2]",
        (
            "Source 1 states that expense claims are due within 30 calendar days. [Source 1]\n"
            "Source 2 states that expense claims are due within 10 calendar days. [Source 2]"
        ),
    ])
    grounding = _ConflictRepairGrounding()
    pipeline = _pipeline_with_documents(docs, llm=llm, grounding_evaluator=grounding)

    result = pipeline.query("What is the expense-claim deadline?")

    assert result["refused"] is False
    assert result["generation_repair"]["attempted"] is True
    assert result["generation_repair"]["accepted"] is True
    assert result["generation_repair"]["reason"] == "repair_passed_grounding"
    assert len(llm.prompts) == 2
    assert "if sources disagree" in llm.prompts[1].lower()
    assert "Source 1 states" in result["answer"]
    assert "Source 2 states" in result["answer"]
    assert result["invalid_citations"] == []


class _GroundsNonAbstention:
    def __init__(self):
        self.calls = []

    def evaluate(self, answer, source_map, source_documents):
        self.calls.append(answer)
        if answer.strip() == ABSTENTION_TEXT:
            return []
        return [{
            "claim": "An Organizational Profile describes an organization's current and/or target cybersecurity posture.",
            "status": "grounded",
            "atomic_claims": [],
        }]


def test_sufficient_evidence_and_model_abstention_trigger_one_recovery_attempt():
    docs = [{
        "text": (
            "A CSF Organizational Profile describes an organization's current "
            "and/or target cybersecurity posture in terms of the Core's outcomes."
        ),
        "score": 6.29,
        "metadata": {"source": "nist_csf_2.0.pdf", "page": 6, "chunk_id": 36},
    }]
    llm = _SequenceLLM([
        ABSTENTION_TEXT,
        "An Organizational Profile describes an organization's current and/or target cybersecurity posture in terms of CSF Core outcomes. [Source 1]",
    ])
    grounding = _GroundsNonAbstention()
    pipeline = _pipeline_with_documents(docs, llm=llm, grounding_evaluator=grounding)

    result = pipeline.query("What is an Organizational Profile?")

    assert result["evidence"]["sufficient"] is True
    assert result["refused"] is False
    assert result["grounding"][0]["status"] == "grounded"
    assert result["invalid_citations"] == []
    assert result["generation_repair"]["attempted"] is True
    assert result["generation_repair"]["mode"] == "answerability_recovery"
    assert result["generation_repair"]["accepted"] is True
    assert result["generation_repair"]["reason"] == "answerability_recovery_passed_grounding"
    assert len(llm.prompts) == 2
    assert "ANSWERABILITY RECOVERY MODE" in llm.prompts[1]


def test_model_abstention_remains_safe_when_recovery_cannot_answer():
    docs = [{
        "text": (
            "A CSF Organizational Profile describes an organization's current "
            "and/or target cybersecurity posture in terms of the Core's outcomes."
        ),
        "score": 6.29,
        "metadata": {"source": "nist_csf_2.0.pdf", "page": 6, "chunk_id": 36},
    }]
    llm = _SequenceLLM([ABSTENTION_TEXT, ABSTENTION_TEXT])
    grounding = _GroundsNonAbstention()
    pipeline = _pipeline_with_documents(docs, llm=llm, grounding_evaluator=grounding)

    result = pipeline.query("What is an Organizational Profile?")

    assert result["evidence"]["sufficient"] is True
    assert result["refused"] is True
    assert result["answer"] == ABSTENTION_TEXT
    assert result["generation_repair"]["attempted"] is True
    assert result["generation_repair"]["accepted"] is False
    assert result["generation_repair"]["reason"] == "answerability_recovery_still_abstained"
    assert len(llm.prompts) == 2


class _GroundedSubsetGrounding:
    """Return a mixed first draft, mixed repair, then validate the subset."""
    def __init__(self):
        self.calls = 0

    def evaluate(self, answer, source_map, source_documents):
        self.calls += 1
        if self.calls == 1:
            return [{
                "claim": "A long combined answer.",
                "status": "unsupported",
                "atomic_claims": [],
            }]
        if self.calls == 2:
            return [{
                "claim": "A long combined answer.",
                "status": "unsupported",
                "atomic_claims": [
                    {
                        "claim": "The CSF translates cybersecurity risk terminology into general risk management language.",
                        "status": "grounded",
                        "sources": [{"source_number": 1, "label": "entailment", "conflict_detected": False}],
                    },
                    {
                        "claim": "Executives provide input about risk activities.",
                        "status": "unsupported",
                        "sources": [{"source_number": 1, "label": "neutral", "conflict_detected": False}],
                    },
                ],
            }]
        assert "The CSF translates cybersecurity risk terminology" in answer
        return [{
            "claim": "The CSF translates cybersecurity risk terminology into general risk management language.",
            "status": "grounded",
            "atomic_claims": [],
        }]


def test_failed_repair_can_return_only_independently_regrounded_atoms():
    docs = [{
        "text": "The CSF translates cybersecurity risk terminology into general risk management language.",
        "score": 6.3,
        "metadata": {"source": "nist_csf_2.0.pdf", "page": 12, "chunk_id": 120},
    }]
    llm = _SequenceLLM([
        "The CSF translates cybersecurity risk terminology into general risk management language. [Source 1] Also, executives provide input about risk activities. [Source 1]",
        "The CSF translates cybersecurity risk terminology into general risk management language. [Source 1] Executives provide input about risk activities. [Source 1]",
    ])
    grounding = _GroundedSubsetGrounding()
    pipeline = _pipeline_with_documents(docs, llm=llm, grounding_evaluator=grounding)

    result = pipeline.query("How are cybersecurity risks integrated into enterprise risk management?")

    assert result["refused"] is False
    assert result["answer"] == (
        "- The CSF translates cybersecurity risk terminology into general risk management language. [Source 1]"
    )
    assert result["generation_repair"]["accepted"] is True
    assert result["generation_repair"]["reason"] == "repair_grounded_subset_passed_grounding"
    assert result["generation_repair"]["grounded_subset_used"] is True
    assert result["invalid_citations"] == []
    assert grounding.calls == 3
