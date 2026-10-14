import json
from pathlib import Path

import pytest

from src.evaluation.document_independent_benchmark import (
    load_suite,
    run_grounding_benchmark,
    run_query_benchmark,
    validate_suite,
    write_report,
)

ROOT = Path(__file__).resolve().parents[2]
SMOKE_SUITE = ROOT / "data/evaluation/benchmarks/cross_domain_grounding.json"
QUERY_TEMPLATE = ROOT / "data/evaluation/benchmarks/query_benchmark_template.json"


def test_cross_domain_suite_is_valid_and_not_single_domain():
    suite = load_suite(SMOKE_SUITE)
    domains = {case["domain"] for case in suite["grounding_cases"]}
    labels = {case["expected_label"] for case in suite["grounding_cases"]}

    assert len(suite["grounding_cases"]) >= 15
    assert len(domains) >= 5
    assert labels == {"entailment", "contradiction", "neutral"}
    assert {case["split"] for case in suite["grounding_cases"]} == {
        "calibration", "held_out"
    }
    assert sum(case["split"] == "held_out" for case in suite["grounding_cases"]) == 6


def test_suite_rejects_undeclared_corpus_id():
    suite = {
        "schema_version": 1,
        "suite_id": "invalid-corpus",
        "corpora": [{"id": "corp-a"}],
        "query_cases": [{
            "id": "q1", "corpus_id": "missing", "query": "Question?", "answerable": True
        }],
        "grounding_cases": [],
    }

    with pytest.raises(ValueError, match="not declared"):
        validate_suite(suite)


class FakeGrounder:
    def __init__(self, wrong=None):
        self.wrong = wrong or {}

    def check_claim(self, claim, evidence):
        label = self.wrong.get((claim, evidence))
        if label is None:
            label = next(
                case["expected_label"]
                for case in SUITE["grounding_cases"]
                if case["claim"] == claim and case["evidence"] == evidence
            )
        return {"label": label, "probabilities": {label: 0.99}}


SUITE = load_suite(SMOKE_SUITE)


def test_grounding_runner_reports_accuracy_and_domain_metrics():
    report = run_grounding_benchmark(SUITE, FakeGrounder())

    assert report["metrics"]["total_cases"] == len(SUITE["grounding_cases"])
    assert report["metrics"]["accuracy"] == 1.0
    assert len(report["by_domain"]) >= 5
    assert report["metrics"]["incorrect_cases"] == 0
    assert report["metrics"]["false_contradiction_rate"] == 0.0
    assert report["metrics"]["macro_f1"] == 1.0
    assert report["by_split"]["held_out"]["accuracy"] == 1.0
    assert report["by_document_format"]["text_pair"]["total_cases"] == 18
    assert len(report["suite_sha256"]) == 64


def test_grounding_runner_exposes_false_contradiction_instead_of_hiding_it():
    case = next(c for c in SUITE["grounding_cases"] if c["id"] == "hr_transport_unrelated")
    grounder = FakeGrounder({(case["claim"], case["evidence"]): "contradiction"})
    report = run_grounding_benchmark(SUITE, grounder)

    failed = next(c for c in report["cases"] if c["case_id"] == "hr_transport_unrelated")
    assert failed["correct"] is False
    assert failed["expected_label"] == "neutral"
    assert failed["predicted_label"] == "contradiction"
    assert report["metrics"]["incorrect_cases"] == 1
    assert report["metrics"]["false_contradiction_rate"] > 0.0


class FakePipeline:
    def __init__(self, outputs):
        self.outputs = outputs
        self.queries = []

    def query(self, question):
        self.queries.append(question)
        return self.outputs[question]


def test_query_runner_is_corpus_agnostic_and_aggregates_refusal_and_grounding():
    suite = {
        "schema_version": 1,
        "suite_id": "query-smoke",
        "corpora": [
            {"id": "hr", "label": "HR corpus", "domain": "hr", "document_format": "docx"},
            {"id": "it", "label": "IT corpus", "domain": "it", "document_format": "csv"},
        ],
        "query_cases": [
            {"id": "hr-ok", "corpus_id": "hr", "query": "Q1", "answerable": True,
             "split": "calibration",
             "required_concept_groups": [["annual leave", "paid leave"]]},
            {"id": "it-refuse", "corpus_id": "it", "query": "Q2", "answerable": False,
             "split": "held_out",
             "required_concept_groups": []},
        ],
        "grounding_cases": [],
    }
    outputs = {
        "Q1": {
            "answer": "The annual leave rule allows 20 days.",
            "refused": False,
            "citations": [{"source_number": 1}],
            "invalid_citations": [],
            "grounding": [{"claim": "The rule allows 20 days", "status": "grounded"}],
            "evidence": {"sufficient": True},
        },
        "Q2": {
            "answer": "Insufficient evidence is available.",
            "refused": True,
            "invalid_citations": [],
            "grounding": [],
            "evidence": {"sufficient": False},
        },
    }
    factories = {}

    def factory(corpus):
        factories[corpus["id"]] = factories.get(corpus["id"], 0) + 1
        return FakePipeline(outputs)

    report = run_query_benchmark(suite, factory)

    assert report["metrics"]["answer_success_rate"] == 1.0
    assert report["metrics"]["refusal_accuracy"] == 1.0
    assert report["metrics"]["citation_validity_rate"] == 1.0
    assert report["metrics"]["grounded_claim_rate"] == 1.0
    assert report["cases"][0]["concept_coverage"]["coverage"] == 1.0
    assert report["by_domain"]["hr"]["answer_success_rate"] == 1.0
    assert report["by_document_format"]["csv"]["refusal_accuracy"] == 1.0
    assert report["by_split"]["held_out"]["refusal_accuracy"] == 1.0
    assert report["by_document_format"]["docx"]["query_count"] == 1
    assert len(report["suite_sha256"]) == 64
    assert factories == {"hr": 1, "it": 1}


def test_metrics_are_null_not_zero_when_the_denominator_does_not_exist():
    suite = {
        "schema_version": 1,
        "suite_id": "no-unanswerable-cases",
        "corpora": [{"id": "c"}],
        "query_cases": [{"id": "q", "corpus_id": "c", "query": "Q", "answerable": True}],
        "grounding_cases": [],
    }

    report = run_query_benchmark(
        suite,
        lambda _: FakePipeline({"Q": {"answer": "ok", "refused": False}}),
    )

    assert report["metrics"]["refusal_accuracy"] is None


def test_report_writer_creates_parent_directory(tmp_path):
    destination = tmp_path / "reports" / "run.json"
    report = {"suite_id": "unit-test", "metrics": {"accuracy": 1.0}}

    written = write_report(report, destination)

    assert written == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == report


def test_suite_rejects_unknown_evaluation_split():
    suite = {
        "schema_version": 1,
        "suite_id": "bad-split",
        "corpora": [{"id": "c"}],
        "query_cases": [{
            "id": "q1", "corpus_id": "c", "query": "Question?",
            "answerable": True, "split": "train-and-test",
        }],
        "grounding_cases": [],
    }

    with pytest.raises(ValueError, match="split must be one of"):
        validate_suite(suite)


def test_corpus_rejects_unknown_split():
    suite = {
        "schema_version": 1,
        "suite_id": "bad-corpus-split",
        "corpora": [{"id": "c", "split": "all-at-once"}],
        "query_cases": [{
            "id": "q1", "corpus_id": "c", "query": "Question?",
            "answerable": True,
        }],
        "grounding_cases": [],
    }

    with pytest.raises(ValueError, match="corpus c: split must be one of"):
        validate_suite(suite)


def test_query_suite_template_is_valid_and_uses_separate_corpora():
    suite = load_suite(QUERY_TEMPLATE)
    assert len(suite["corpora"]) == 2
    assert {corpus["split"] for corpus in suite["corpora"]} == {
        "calibration", "held_out"
    }
    assert {case["split"] for case in suite["query_cases"]} == {
        "calibration", "held_out"
    }


def test_answerable_empty_answer_is_not_answer_success(tmp_path):
    suite = {
        "schema_version": 1,
        "suite_id": "empty-answer",
        "corpora": [{"id": "c", "document_format": "pdf"}],
        "query_cases": [{
            "id": "q1", "corpus_id": "c", "query": "Question?",
            "answerable": True,
        }],
        "grounding_cases": [],
    }
    result = {
        "answer": "  ", "refused": False,
        "citations": [], "invalid_citations": [], "grounding": [],
    }
    report = run_query_benchmark(suite, lambda _: FakePipeline({"Question?": result}))
    assert report["metrics"]["answer_success_rate"] == 0.0
    assert report["metrics"]["citation_validity_rate"] == 0.0


def test_unknown_claim_status_is_reported_not_ignored():
    suite = {
        "schema_version": 1,
        "suite_id": "unknown-grounding-status",
        "corpora": [{"id": "c"}],
        "query_cases": [{
            "id": "q1", "corpus_id": "c", "query": "Question?",
            "answerable": True,
        }],
        "grounding_cases": [],
    }
    result = {
        "answer": "An answer.", "refused": False,
        "citations": [{"source_number": 1}], "invalid_citations": [],
        "grounding": [{"claim": "A claim", "status": "maybe"}],
    }
    report = run_query_benchmark(suite, lambda _: FakePipeline({"Question?": result}))
    assert report["claim_counts"]["unknown"] == 1
    assert report["metrics"]["grounded_claim_rate"] == 0.0


def test_acceptance_gates_are_suite_specific_and_report_failures():
    suite = {
        "schema_version": 1,
        "suite_id": "suite-specific-gates",
        "corpora": [{"id": "c", "domain": "operations"}],
        "query_cases": [
            {"id": "answerable", "corpus_id": "c", "query": "Q1", "answerable": True},
            {"id": "unanswerable", "corpus_id": "c", "query": "Q2", "answerable": False},
        ],
        "grounding_cases": [],
        "acceptance_gates": {
            "minimum_answer_success_rate": 1.0,
            "minimum_refusal_accuracy": 1.0,
            "minimum_citation_validity_rate": 1.0,
        },
    }
    outputs = {
        "Q1": {
            "answer": "Answer", "refused": False,
            "citations": [], "invalid_citations": [],
            "grounding": [],
        },
        "Q2": {
            "answer": "Best guess", "refused": False,
            "citations": [], "invalid_citations": [], "grounding": [],
        },
    }
    report = run_query_benchmark(
        suite,
        lambda _: FakePipeline(outputs),
    )
    assert report["acceptance_gates"]["configured"] is True
    assert report["acceptance_gates"]["passed"] is False
    statuses = {item["metric"]: item["passed"] for item in report["acceptance_gates"]["checks"]}
    assert statuses["answer_success_rate"] is True
    assert statuses["refusal_accuracy"] is False
    assert statuses["citation_validity_rate"] is False


def test_no_global_thresholds_are_imposed_when_suite_has_no_gates():
    suite = {
        "schema_version": 1,
        "suite_id": "diagnostic-only",
        "corpora": [{"id": "c"}],
        "query_cases": [{"id": "q", "corpus_id": "c", "query": "Q", "answerable": True}],
        "grounding_cases": [],
    }
    result = {
        "answer": "A useful answer", "refused": False,
        "citations": [{"source_number": 1}], "invalid_citations": [],
        "grounding": [],
    }
    report = run_query_benchmark(suite, lambda _: FakePipeline({"Q": result}))
    assert report["acceptance_gates"]["configured"] is False
    assert report["acceptance_gates"]["passed"] is None


def test_acceptance_gate_values_must_be_rates_between_zero_and_one():
    suite = {
        "schema_version": 1,
        "suite_id": "invalid-gate",
        "corpora": [{"id": "c"}],
        "query_cases": [{"id": "q", "corpus_id": "c", "query": "Q", "answerable": True}],
        "grounding_cases": [],
        "acceptance_gates": {"minimum_answer_success_rate": 1.1},
    }
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_suite(suite)
