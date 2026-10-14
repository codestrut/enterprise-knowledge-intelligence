"""Fast tests for answerability accounting in the framework evaluation runner.

These tests monkeypatch the pipeline with controlled outputs. They do not load
local transformer models, retrieve documents, or make external calls.
"""
import asyncio
from types import SimpleNamespace

from scripts import run_framework_eval as eval_runner


ABSTENTION = "I don't have sufficient evidence in the available knowledge base to answer that question."


class FakePipeline:
    def __init__(self, *, document_path, retrieval_backend, outputs):
        self.document_path = document_path
        self.retrieval_backend = retrieval_backend
        self.outputs = outputs
        self.chunks = []

    def query(self, question):
        return self.outputs[question]


def _args(tmp_path):
    return SimpleNamespace(
        document="tests/fixtures/fake-corpus.pdf",
        backend="custom",
        with_ragas=False,
        limit=None,
        include_grounding_details=False,
        include_text=True,
        report=str(tmp_path / "report.json"),
    )


def _refusal():
    return {
        "answer": ABSTENTION,
        "refused": True,
        "invalid_citations": [],
        "citations": [],
        "sources": [],
        "grounding": [],
        "evidence": {"sufficient": True, "score": 6.29, "threshold": 4.3,
                     "reason": "Evidence passed the relevance threshold."},
        "generation_repair": {"attempted": True, "accepted": False,
                              "reason": "recovery_returned_abstention"},
    }


def _supported_answer():
    return {
        "answer": "An Organizational Profile describes an organization's current or target cybersecurity posture in terms of the CSF Core outcomes. [Source 1]",
        "refused": False,
        "invalid_citations": [],
        "citations": [{"source_number": 1}],
        "sources": [],
        "grounding": [{"claim": "An Organizational Profile describes an organization's current or target cybersecurity posture in terms of the CSF Core outcomes.",
                       "status": "grounded"}],
        "evidence": {"sufficient": True, "score": 6.29, "threshold": 4.3,
                     "reason": "Evidence passed the relevance threshold."},
        "generation_repair": {"attempted": False, "accepted": False,
                              "reason": "initial_answer_passed_grounding"},
    }


def _run(monkeypatch, tmp_path, dataset, outputs):
    def factory(*, document_path, retrieval_backend):
        return FakePipeline(
            document_path=document_path,
            retrieval_backend=retrieval_backend,
            outputs=outputs,
        )

    monkeypatch.setattr(eval_runner, "RAGPipeline", factory)
    monkeypatch.setattr(eval_runner, "EVALUATION_DATASET", dataset)
    return asyncio.run(eval_runner.run(_args(tmp_path)))


def test_answerable_query_refused_by_generation_is_counted_as_failure(monkeypatch, tmp_path):
    query = "What is an Organizational Profile?"
    report = _run(
        monkeypatch, tmp_path,
        [{"query": query, "answerable": True, "relevant_chunks": []}],
        {query: _refusal()},
    )

    assert report["metrics"]["answer_success_rate"] == 0.0
    assert report["queries"][0]["answerable"] is True
    assert report["queries"][0]["refused"] is True
    assert report["queries"][0]["answered"] is False
    assert report["queries"][0]["evidence_gate"]["sufficient"] is True
    assert report["queries"][0]["generation_repair"]["attempted"] is True


def test_supported_answer_to_answerable_query_is_counted_as_success(monkeypatch, tmp_path):
    query = "What is an Organizational Profile?"
    report = _run(
        monkeypatch, tmp_path,
        [{"query": query, "answerable": True, "relevant_chunks": []}],
        {query: _supported_answer()},
    )

    assert report["metrics"]["answer_success_rate"] == 1.0
    assert report["metrics"]["grounded_answer_rate"] == 1.0
    assert report["queries"][0]["answered"] is True
    assert report["queries"][0]["grounding_statuses"] == ["grounded"]


def test_unanswerable_query_refusal_is_counted_as_correct(monkeypatch, tmp_path):
    query = "What is the default password for a Cisco firewall?"
    report = _run(
        monkeypatch, tmp_path,
        [{"query": query, "answerable": False, "relevant_chunks": []}],
        {query: _refusal()},
    )

    assert report["metrics"]["refusal_accuracy"] == 1.0
    assert report["queries"][0]["refused"] is True
    assert report["queries"][0]["answered"] is False
