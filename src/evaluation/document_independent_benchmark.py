"""Corpus-agnostic benchmark helpers for EKIP.

This module intentionally uses only the Python standard library. A benchmark
suite supplies its own corpora, questions, expected answerability, and labelled
claim/evidence pairs. The runner does not hard-code any domain, document path,
retrieval-score scale, or corpus-specific threshold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol


ALLOWED_RELATIONS = {"entailment", "contradiction", "neutral"}
ALLOWED_GROUNDING_STATUSES = {"grounded", "unsupported", "contradicted"}
UNKNOWN_GROUNDING_STATUS = "unknown"
ALLOWED_SPLITS = {"calibration", "validation", "held_out", "test", "unspecified"}
ACCEPTANCE_GATE_OPERATORS = {
    "minimum_answer_success_rate": ("answer_success_rate", ">="),
    "minimum_refusal_accuracy": ("refusal_accuracy", ">="),
    "minimum_citation_validity_rate": ("citation_validity_rate", ">="),
    "minimum_grounded_claim_rate": ("grounded_claim_rate", ">="),
    "minimum_fully_grounded_answer_rate_answerable": (
        "fully_grounded_answer_rate_answerable", ">="
    ),
    "maximum_unsupported_claim_rate": ("unsupported_claim_rate", "<="),
    "maximum_contradicted_claim_rate": ("contradicted_claim_rate", "<="),
}


class QueryPipeline(Protocol):
    """Minimal contract required by the generic query benchmark."""

    def query(self, question: str) -> Mapping[str, Any]: ...


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_suite(suite: Mapping[str, Any]) -> None:
    """Validate a JSON-compatible benchmark suite with actionable errors."""
    if not isinstance(suite, Mapping):
        raise ValueError("Benchmark suite must be a JSON object.")
    if suite.get("schema_version") != 1:
        raise ValueError("schema_version must be 1.")
    if not _non_empty_string(suite.get("suite_id")):
        raise ValueError("suite_id must be a non-empty string.")

    corpora = suite.get("corpora", [])
    query_cases = suite.get("query_cases", [])
    grounding_cases = suite.get("grounding_cases", [])

    if not isinstance(corpora, list):
        raise ValueError("corpora must be a list.")
    if not isinstance(query_cases, list):
        raise ValueError("query_cases must be a list.")
    if not isinstance(grounding_cases, list):
        raise ValueError("grounding_cases must be a list.")
    if not query_cases and not grounding_cases:
        raise ValueError("Suite must contain query_cases or grounding_cases.")

    acceptance_gates = suite.get("acceptance_gates", {})
    if not isinstance(acceptance_gates, Mapping):
        raise ValueError("acceptance_gates must be an object when provided.")
    for key, value in acceptance_gates.items():
        if key not in ACCEPTANCE_GATE_OPERATORS:
            raise ValueError(
                f"Unknown acceptance gate {key!r}; supported gates are "
                f"{sorted(ACCEPTANCE_GATE_OPERATORS)}."
            )
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            raise ValueError(f"acceptance_gates.{key} must be a number between 0 and 1.")

    corpus_ids: set[str] = set()
    for index, corpus in enumerate(corpora):
        if not isinstance(corpus, Mapping):
            raise ValueError(f"corpora[{index}] must be an object.")
        corpus_id = corpus.get("id")
        if not _non_empty_string(corpus_id):
            raise ValueError(f"corpora[{index}].id must be a non-empty string.")
        if corpus_id in corpus_ids:
            raise ValueError(f"Duplicate corpus id: {corpus_id}.")
        corpus_split = corpus.get("split")
        if corpus_split is not None and corpus_split not in ALLOWED_SPLITS:
            raise ValueError(
                f"corpus {corpus_id}: split must be one of {sorted(ALLOWED_SPLITS)}."
            )
        corpus_ids.add(corpus_id)

    query_ids: set[str] = set()
    for index, case in enumerate(query_cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"query_cases[{index}] must be an object.")
        case_id = case.get("id")
        if not _non_empty_string(case_id):
            raise ValueError(f"query_cases[{index}].id must be a non-empty string.")
        if case_id in query_ids:
            raise ValueError(f"Duplicate query case id: {case_id}.")
        query_ids.add(case_id)
        if not _non_empty_string(case.get("query")):
            raise ValueError(f"query case {case_id}: query must be non-empty.")
        if not isinstance(case.get("answerable"), bool):
            raise ValueError(f"query case {case_id}: answerable must be boolean.")
        corpus_id = case.get("corpus_id")
        if corpus_id not in corpus_ids:
            raise ValueError(
                f"query case {case_id}: corpus_id {corpus_id!r} is not declared in corpora."
            )
        split = case.get("split", "unspecified")
        if split not in ALLOWED_SPLITS:
            raise ValueError(
                f"query case {case_id}: split must be one of {sorted(ALLOWED_SPLITS)}."
            )
        document_format = case.get("document_format")
        if document_format is not None and not _non_empty_string(document_format):
            raise ValueError(
                f"query case {case_id}: document_format must be a non-empty string when provided."
            )
        require_citations = case.get("require_citations")
        if require_citations is not None and not isinstance(require_citations, bool):
            raise ValueError(
                f"query case {case_id}: require_citations must be boolean when provided."
            )
        concept_groups = case.get("required_concept_groups", [])
        if not isinstance(concept_groups, list):
            raise ValueError(
                f"query case {case_id}: required_concept_groups must be a list."
            )
        for group_index, group in enumerate(concept_groups):
            if (
                not isinstance(group, list)
                or not group
                or not all(_non_empty_string(alias) for alias in group)
            ):
                raise ValueError(
                    f"query case {case_id}: concept group {group_index} must be a non-empty list of strings."
                )

    grounding_ids: set[str] = set()
    for index, case in enumerate(grounding_cases):
        if not isinstance(case, Mapping):
            raise ValueError(f"grounding_cases[{index}] must be an object.")
        case_id = case.get("id")
        if not _non_empty_string(case_id):
            raise ValueError(f"grounding_cases[{index}].id must be a non-empty string.")
        if case_id in grounding_ids:
            raise ValueError(f"Duplicate grounding case id: {case_id}.")
        grounding_ids.add(case_id)
        for field in ("domain", "claim", "evidence"):
            if not _non_empty_string(case.get(field)):
                raise ValueError(
                    f"grounding case {case_id}: {field} must be a non-empty string."
                )
        split = case.get("split", "unspecified")
        if split not in ALLOWED_SPLITS:
            raise ValueError(
                f"grounding case {case_id}: split must be one of {sorted(ALLOWED_SPLITS)}."
            )
        expected = case.get("expected_label")
        if expected not in ALLOWED_RELATIONS:
            raise ValueError(
                f"grounding case {case_id}: expected_label must be one of {sorted(ALLOWED_RELATIONS)}."
            )


def load_suite(path: str | Path) -> dict[str, Any]:
    """Load and validate a suite from JSON."""
    suite_path = Path(path)
    try:
        suite = json.loads(suite_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Could not read benchmark suite {suite_path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Benchmark suite {suite_path} is not valid JSON: {exc}"
        ) from exc
    validate_suite(suite)
    return suite


def _normalise_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def _concept_coverage(answer: str, groups: list[list[str]]) -> dict[str, Any] | None:
    """Auxiliary exact-alias coverage; useful for diagnostics, not a sole quality gate."""
    if not groups:
        return None
    normalized_answer = f" {_normalise_text(answer)} "
    matched = []
    missing = []
    for group in groups:
        match = next(
            (alias for alias in group if f" {_normalise_text(alias)} " in normalized_answer),
            None,
        )
        (matched if match is not None else missing).append(
            {"aliases": group, "matched_alias": match}
            if match is not None
            else {"aliases": group}
        )
    return {
        "matched_groups": len(matched),
        "total_groups": len(groups),
        "coverage": len(matched) / len(groups),
        "matched": matched,
        "missing": missing,
    }


def _claim_status_counts(grounding: Any) -> dict[str, int]:
    counts = Counter({status: 0 for status in ALLOWED_GROUNDING_STATUSES})
    counts[UNKNOWN_GROUNDING_STATUS] = 0
    if not isinstance(grounding, list):
        return dict(counts)
    for claim in grounding:
        if not isinstance(claim, Mapping):
            continue
        atomic_claims = claim.get("atomic_claims")
        statuses = (
            [item.get("status") for item in atomic_claims if isinstance(item, Mapping)]
            if isinstance(atomic_claims, list) and atomic_claims
            else [claim.get("status")]
        )
        for status in statuses:
            if status in ALLOWED_GROUNDING_STATUSES:
                counts[status] += 1
            else:
                counts[UNKNOWN_GROUNDING_STATUS] += 1
    return dict(counts)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _suite_sha256(suite: Mapping[str, Any]) -> str:
    """Return a deterministic fingerprint for the benchmark data/config."""
    canonical = json.dumps(
        suite,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _summarize_query_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize one query group; empty denominators are reported as null."""
    answerable = [case for case in cases if case["answerable"]]
    unanswerable = [case for case in cases if not case["answerable"]]
    total_claims_by_status: Counter[str] = Counter()
    for case in cases:
        total_claims_by_status.update(case["claim_status_counts"])
    total_claims = sum(total_claims_by_status.values())
    concept_cases = [case for case in cases if case["concept_coverage"] is not None]
    answered_answerable = [case for case in answerable if not case["refused"]]

    return {
        "query_count": len(cases),
        "answerable_query_count": len(answerable),
        "unanswerable_query_count": len(unanswerable),
        "answer_success_rate": _safe_rate(
            sum(case["answer_success"] for case in answerable), len(answerable)
        ),
        "refusal_accuracy": _safe_rate(
            sum(case["refused"] for case in unanswerable), len(unanswerable)
        ),
        "citation_validity_rate": _safe_rate(
            sum(case["citation_valid"] for case in cases), len(cases)
        ),
        "grounded_claim_rate": _safe_rate(
            total_claims_by_status["grounded"], total_claims
        ),
        "unsupported_claim_rate": _safe_rate(
            total_claims_by_status["unsupported"], total_claims
        ),
        "contradicted_claim_rate": _safe_rate(
            total_claims_by_status["contradicted"], total_claims
        ),
        "fully_grounded_answer_rate_answerable": _safe_rate(
            sum(case["fully_grounded"] for case in answerable), len(answerable)
        ),
        "fully_grounded_rate_of_answered_answerable": _safe_rate(
            sum(case["fully_grounded"] for case in answered_answerable),
            len(answered_answerable),
        ),
        "mean_required_concept_coverage": _safe_rate(
            round(sum(case["concept_coverage"]["coverage"] for case in concept_cases), 8),
            len(concept_cases),
        ),
        "claim_counts": {
            status: total_claims_by_status[status]
            for status in sorted(ALLOWED_GROUNDING_STATUSES | {UNKNOWN_GROUNDING_STATUS})
        },
    }


def _group_summaries(
    cases: list[dict[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        groups[str(case.get(field) or "unspecified")].append(case)
    return {
        key: _summarize_query_cases(groups[key])
        for key in sorted(groups)
    }


def _evaluate_acceptance_gates(
    suite: Mapping[str, Any], metrics: Mapping[str, Any]
) -> dict[str, Any]:
    """Apply only the gates explicitly declared by this benchmark suite.

    No score or pass threshold is imposed globally. Missing metrics fail a
    configured gate rather than being interpreted as zero or as success.
    """
    checks = []
    for key, expected in suite.get("acceptance_gates", {}).items():
        metric_name, operator = ACCEPTANCE_GATE_OPERATORS[key]
        actual = metrics.get(metric_name)
        passed = (
            actual is not None
            and (actual >= expected if operator == ">=" else actual <= expected)
        )
        checks.append({
            "gate": key,
            "metric": metric_name,
            "operator": operator,
            "expected": expected,
            "actual": actual,
            "passed": passed,
            "reason": None if actual is not None else "Metric has no applicable cases.",
        })
    return {
        "configured": bool(checks),
        "passed": all(item["passed"] for item in checks) if checks else None,
        "checks": checks,
    }


def run_query_benchmark(
    suite: Mapping[str, Any],
    pipeline_factory: Callable[[Mapping[str, Any]], QueryPipeline],
) -> dict[str, Any]:
    """Run corpus-specific labelled queries through an arbitrary pipeline adapter.

    The harness itself makes no assumptions about file formats, vector stores,
    retrieval-score scales, tenant implementation, or application framework.
    The pipeline factory receives each corpus config and should return an object
    with ``query(question)`` returning EKIP's normalized result contract.
    """
    validate_suite(suite)
    corpora = {corpus["id"]: corpus for corpus in suite.get("corpora", [])}
    pipelines: dict[str, QueryPipeline] = {}
    case_results: list[dict[str, Any]] = []

    for case in suite.get("query_cases", []):
        corpus_id = case["corpus_id"]
        if corpus_id not in pipelines:
            pipelines[corpus_id] = pipeline_factory(corpora[corpus_id])

        result = pipelines[corpus_id].query(case["query"])
        if not isinstance(result, Mapping):
            raise TypeError(
                f"Pipeline result for case {case['id']} must be a mapping."
            )
        refused = bool(result.get("refused", False))
        answer = str(result.get("answer", ""))
        answered = not refused and bool(answer.strip())
        invalid_citations = result.get("invalid_citations", []) or []
        citations = result.get("citations", []) or []
        require_citations = case.get("require_citations", case["answerable"])
        citation_valid = (
            len(invalid_citations) == 0
            and (not require_citations or len(citations) > 0)
        )
        statuses = _claim_status_counts(result.get("grounding", []))
        total_grounded_claims = sum(statuses.values())
        fully_grounded = (
            total_grounded_claims > 0
            and statuses["grounded"] == total_grounded_claims
        )
        concept_report = _concept_coverage(
            answer,
            case.get("required_concept_groups", []),
        )
        corpus_config = corpora[corpus_id]
        case_results.append({
            "case_id": case["id"],
            "corpus_id": corpus_id,
            "domain": case.get("domain", corpus_config.get("domain", "unspecified")),
            "document_format": case.get(
                "document_format", corpus_config.get("document_format", "unspecified")
            ),
            "split": case.get("split", corpus_config.get("split", "unspecified")),
            "answerable": case["answerable"],
            "refused": refused,
            "answered": answered,
            "answer_success": case["answerable"] and answered,
            "refusal_correct": (not case["answerable"]) and refused,
            "citation_required": require_citations,
            "citation_count": len(citations),
            "citation_valid": citation_valid,
            "invalid_citation_count": len(invalid_citations),
            "claim_status_counts": statuses,
            "fully_grounded": fully_grounded,
            "concept_coverage": concept_report,
            "evidence_sufficient": (result.get("evidence") or {}).get("sufficient"),
        })

    overall = _summarize_query_cases(case_results)
    public_metrics = {key: value for key, value in overall.items() if key != "claim_counts"}
    acceptance_report = _evaluate_acceptance_gates(suite, public_metrics)
    return {
        "schema_version": 1,
        "suite_id": suite["suite_id"],
        "suite_sha256": _suite_sha256(suite),
        "suite_schema_version": suite["schema_version"],
        "code_revision": suite.get("code_revision"),
        "run_type": "query",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": public_metrics,
        "acceptance_gates": acceptance_report,
        "claim_counts": overall["claim_counts"],
        "by_domain": _group_summaries(case_results, "domain"),
        "by_document_format": _group_summaries(case_results, "document_format"),
        "by_split": _group_summaries(case_results, "split"),
        "cases": case_results,
        "notes": [
            "Metrics with no applicable cases are null, not zero.",
            "Missing/unknown grounding statuses are counted explicitly rather than silently ignored.",
            "Answerable query cases require a citation by default; set require_citations explicitly only when a reviewed test does not require one.",
            "Required-concept coverage is an exact-alias diagnostic and must not be the sole quality gate.",
            "Contradicted-claim rate is descriptive; correctness must be judged against labelled claim/evidence cases.",
            "A benchmark result is only as representative as its labelled cases and corpus coverage.",
        ],
    }


def _classification_metrics(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute label-aware metrics so false contradictions are distinguishable."""
    labels = sorted(ALLOWED_RELATIONS)
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for case in case_results:
        confusion[case["expected_label"]][case["predicted_label"]] += 1

    per_label: dict[str, dict[str, Any]] = {}
    f1_values = []
    for label in labels:
        tp = confusion[label][label]
        support = sum(confusion[label].values())
        predicted_count = sum(confusion[expected][label] for expected in labels)
        fp = predicted_count - tp
        fn = support - tp
        precision = _safe_rate(tp, tp + fp)
        recall = _safe_rate(tp, tp + fn)
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall > 0
            else (0.0 if support else None)
        )
        per_label[label] = {
            "support": support,
            "true_positive": tp,
            "false_positive": fp,
            "false_negative": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
        if f1 is not None:
            f1_values.append(f1)

    expected_not_contradicted = [
        case for case in case_results if case["expected_label"] != "contradiction"
    ]
    expected_non_entailment = [
        case for case in case_results if case["expected_label"] != "entailment"
    ]
    total = len(case_results)
    correct = sum(case["correct"] for case in case_results)
    return {
        "total_cases": total,
        "correct_cases": correct,
        "incorrect_cases": total - correct,
        "accuracy": _safe_rate(correct, total),
        "macro_f1": _safe_rate(sum(f1_values), len(f1_values)),
        "false_contradiction_rate": _safe_rate(
            sum(case["predicted_label"] == "contradiction" for case in expected_not_contradicted),
            len(expected_not_contradicted),
        ),
        "false_support_rate": _safe_rate(
            sum(case["predicted_label"] == "entailment" for case in expected_non_entailment),
            len(expected_non_entailment),
        ),
        "per_label": per_label,
    }


def _group_grounding_results(
    case_results: list[dict[str, Any]], field: str
) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in case_results:
        groups[str(case.get(field) or "unspecified")].append(case)
    return {
        key: _classification_metrics(groups[key])
        for key in sorted(groups)
    }


def run_grounding_benchmark(
    suite: Mapping[str, Any],
    grounder: Any,
) -> dict[str, Any]:
    """Compare a SemanticGrounder-like component with labelled claim/evidence pairs."""
    validate_suite(suite)
    case_results = []
    for case in suite.get("grounding_cases", []):
        result = grounder.check_claim(case["claim"], case["evidence"])
        predicted = result.get("label", "unknown")
        raw_predicted = result.get("raw_label", predicted)
        relation_guard = result.get("relation_guard", {})
        if not isinstance(relation_guard, Mapping):
            relation_guard = {}
        support_guard = result.get("support_guard", {})
        if not isinstance(support_guard, Mapping):
            support_guard = {}
        expected = case["expected_label"]
        probabilities = result.get("probabilities", {})
        confidence = (
            probabilities.get(predicted)
            if isinstance(probabilities, Mapping)
            else None
        )
        case_results.append({
            "case_id": case["id"],
            "domain": case["domain"],
            "document_type": case.get("document_type", "text passage"),
            "document_format": case.get("document_format", "text"),
            "split": case.get("split", "unspecified"),
            "expected_label": expected,
            "predicted_label": predicted,
            "raw_predicted_label": raw_predicted,
            "relation_guard_applied": bool(relation_guard.get("applied", False)),
            "relation_guard_reason": relation_guard.get("reason"),
            "shared_content_terms": relation_guard.get("shared_content_terms", []),
            "support_guard_applied": bool(support_guard.get("applied", False)),
            "support_guard_reason": support_guard.get("reason"),
            "support_guard_term_coverage": support_guard.get("term_coverage"),
            "support_guard_ordered_coverage": support_guard.get("ordered_coverage"),
            "support_guard_protected_markers_match": support_guard.get("protected_markers_match"),
            "correct": predicted == expected,
            "predicted_label_confidence": confidence,
            "probabilities": dict(probabilities) if isinstance(probabilities, Mapping) else {},
            "claim": case["claim"],
            "evidence": case["evidence"],
            "rationale": case.get("rationale", ""),
        })

    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    for item in case_results:
        confusion[item["expected_label"]][item["predicted_label"]] += 1

    return {
        "schema_version": 1,
        "suite_id": suite["suite_id"],
        "suite_sha256": _suite_sha256(suite),
        "suite_schema_version": suite["schema_version"],
        "code_revision": suite.get("code_revision"),
        "grounder_model": (
            suite.get("grounder_model")
            or getattr(grounder, "model_name", None)
            or getattr(
                getattr(getattr(getattr(grounder, "model", None), "model", None), "config", None),
                "_name_or_path",
                None,
            )
        ),
        "run_type": "grounding",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "metrics": _classification_metrics(case_results),
        "confusion_matrix": {
            expected: {
                predicted: confusion.get(expected, Counter())[predicted]
                for predicted in sorted(ALLOWED_RELATIONS | {"unknown"})
            }
            for expected in sorted(ALLOWED_RELATIONS)
        },
        "by_domain": _group_grounding_results(case_results, "domain"),
        "by_document_format": _group_grounding_results(case_results, "document_format"),
        "by_split": _group_grounding_results(case_results, "split"),
        "cases": case_results,
        "notes": [
            "This is a diagnostic benchmark, not a guarantee of real-world accuracy.",
            "An expected neutral but predicted contradiction is a false contradiction and must remain visible.",
            "Use held-out examples for generalization checks; do not tune only against this smoke suite.",
        ],
    }


def write_report(report: Mapping[str, Any], path: str | Path) -> Path:
    """Write a portable JSON report, creating the target directory as needed."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Run EKIP's corpus-agnostic grounding benchmark."
    )
    parser.add_argument("--suite", required=True, help="Path to benchmark suite JSON.")
    parser.add_argument("--report", required=True, help="Output JSON report path.")
    args = parser.parse_args()

    suite = load_suite(args.suite)
    if not suite.get("grounding_cases"):
        parser.error("The provided suite contains no grounding_cases.")

    # Lazy import: the benchmark harness and its unit tests do not need to
    # load an NLP model. Only this explicit command loads the configured NLI model.
    from src.generation.semantic_grounder import SemanticGrounder

    model_name = suite.get("grounder_model", "cross-encoder/nli-deberta-v3-base")
    report = run_grounding_benchmark(suite, SemanticGrounder(model_name=model_name))
    output = write_report(report, args.report)
    print(f"Suite: {report['suite_id']}")
    print(f"Cases: {report['metrics']['total_cases']}")
    print(f"Accuracy: {report['metrics']['accuracy']}")
    print(f"Incorrect: {report['metrics']['incorrect_cases']}")
    print(f"Report: {output}")
    for case in report["cases"]:
        if case.get("support_guard_applied"):
            print(
                f"SUPPORT RECOVERY {case['case_id']} [{case['domain']}]: "
                f"raw={case['raw_predicted_label']} effective={case['predicted_label']} "
                f"coverage={case.get('support_guard_term_coverage')} "
                f"ordered={case.get('support_guard_ordered_coverage')}"
            )
            print(f"  Guard: {case.get('support_guard_reason')}")
        if not case["correct"]:
            print(
                f"FAIL {case['case_id']} [{case['domain']}]: "
                f"expected={case['expected_label']} "
                f"raw={case['raw_predicted_label']} "
                f"effective={case['predicted_label']}"
            )
            if case.get("relation_guard_applied"):
                print(f"  Guard: {case.get('relation_guard_reason')}")
                print(f"  Shared content terms: {case.get('shared_content_terms')}")
    return 0 if report["metrics"]["incorrect_cases"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(_main())
