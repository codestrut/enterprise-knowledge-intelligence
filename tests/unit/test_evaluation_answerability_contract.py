"""Protect the frozen MVP answerability labels from accidental drift.

These are fast data-contract tests: they do not invoke an LLM or rerun retrieval.
The direct pipeline recovery behavior is covered by
``test_refusal_conflict_regressions.py``.
"""

from src.evaluation.retrieval_eval import EVALUATION_DATASET


ORGANIZATIONAL_PROFILE_QUERY = "What is an Organizational Profile?"
EXPECTED_UNANSWERABLE_QUERIES = {
    "What does the NIST CSF 2.0 say about implementation costs?",
    "Which encryption algorithm does the NIST CSF 2.0 require organizations to use?",
    "What is the default password for a Cisco firewall?",
    "What is the latest Windows security vulnerability?",
}


def _by_query():
    return {case["query"]: case for case in EVALUATION_DATASET}


def test_organizational_profile_false_refusal_regression_stays_answerable():
    case = _by_query()[ORGANIZATIONAL_PROFILE_QUERY]

    assert case["answerable"] is True
    concepts = " ".join(case.get("expected_concepts", [])).lower()
    assert "current and/or target cybersecurity posture" in concepts
    assert "csf core outcomes" in concepts


def test_all_four_unanswerable_regression_cases_remain_explicit():
    cases = _by_query()

    assert EXPECTED_UNANSWERABLE_QUERIES.issubset(cases)
    for query in EXPECTED_UNANSWERABLE_QUERIES:
        assert cases[query]["answerable"] is False, query
        assert cases[query]["expected_concepts"] == [], query


def test_evaluation_queries_are_unique_and_answerability_labels_are_boolean():
    queries = [case["query"] for case in EVALUATION_DATASET]

    assert len(queries) == len(set(queries)), "Duplicate evaluation queries detected"
    assert all(isinstance(case.get("answerable"), bool) for case in EVALUATION_DATASET)
