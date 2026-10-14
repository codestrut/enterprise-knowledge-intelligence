
import pytest

from src.generation.evidence_gate import (
    DEFAULT_THRESHOLD,
    check_evidence,
)


def make_document(score, text="Sample evidence"):
    return {
        "text": text,
        "score": score,
    }


def test_empty_retrieval_is_insufficient():
    result = check_evidence([])

    assert result["sufficient"] is False
    assert result["score"] is None


def test_evidence_above_threshold_is_sufficient():
    result = check_evidence([
        make_document(4.548)
    ])

    assert result["sufficient"] is True
    assert result["score"] == pytest.approx(4.548)


def test_evidence_below_threshold_is_insufficient():
    result = check_evidence([
        make_document(4.134)
    ])

    assert result["sufficient"] is False


def test_negative_relevance_score_is_insufficient():
    result = check_evidence([
        make_document(-8.827)
    ])

    assert result["sufficient"] is False


def test_best_retrieved_score_is_used():
    result = check_evidence([
        make_document(1.2),
        make_document(4.548),
        make_document(2.1),
    ])

    assert result["sufficient"] is True
    assert result["score"] == pytest.approx(4.548)


def test_blank_evidence_is_ignored():
    result = check_evidence([
        make_document(10.0, text="   "),
    ])

    assert result["sufficient"] is False


def test_missing_scores_fail_closed():
    result = check_evidence([
        {"text": "Evidence with no score"},
    ])

    assert result["sufficient"] is False


def test_default_threshold_is_explicit():
    assert DEFAULT_THRESHOLD == pytest.approx(4.3)


def test_threshold_is_required():
    with pytest.raises(ValueError):
        check_evidence(
            [make_document(5.0)],
            threshold=None,
        )
