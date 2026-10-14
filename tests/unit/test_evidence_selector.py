"""Unit tests for evidence selection and failure handling."""

import pytest

from src.generation.evidence_selector import EvidenceSelector


@pytest.fixture
def selector():
    """Create an evidence selector for testing."""
    return EvidenceSelector(similarity_threshold=0.30)


@pytest.fixture
def organizational_evidence():
    """Provide sample cybersecurity framework evidence."""
    return (
        "An Organizational Profile describes an organization's "
        "current and/or target cybersecurity posture in terms of "
        "the CSF Core outcomes. "
        "Organizations can use Profiles to understand, tailor, "
        "assess, prioritize, and communicate cybersecurity outcomes. "
        "The CSF includes five Functions: Identify, Protect, Detect, "
        "Respond, and Recover."
    )


def test_select_returns_relevant_evidence(
    selector,
    organizational_evidence,
):
    """Relevant profile evidence should rank above unrelated text."""

    results = selector.select(
        claim=(
            "An Organizational Profile describes an organization's "
            "current and target cybersecurity posture."
        ),
        evidence=organizational_evidence,
        top_k=2,
    )

    assert results
    assert len(results) <= 2
    assert any(
        "Organizational Profile" in result["text"]
        for result in results
    )

    for result in results:
        assert "text" in result
        assert "score" in result
        assert "semantic_score" in result
        assert "lexical_score" in result


def test_empty_claim_returns_no_evidence(
    selector,
    organizational_evidence,
):
    """An empty claim should return no results."""

    assert selector.select(
        claim="",
        evidence=organizational_evidence,
        top_k=2,
    ) == []


def test_empty_evidence_returns_no_results(selector):
    """Empty evidence should return no results."""

    assert selector.select(
        claim="What is an Organizational Profile?",
        evidence="",
        top_k=2,
    ) == []


def test_invalid_top_k_raises_value_error(
    selector,
    organizational_evidence,
):
    """A non-positive top_k should raise ValueError."""

    with pytest.raises(
        ValueError,
        match="top_k must be at least 1",
    ):
        selector.select(
            claim="What is an Organizational Profile?",
            evidence=organizational_evidence,
            top_k=0,
        )


def test_unrelated_claim_does_not_select_evidence(selector):
    """An unrelated claim should not match unrelated evidence."""

    results = selector.select(
        claim=(
            "The organization operates a fleet "
            "of commercial aircraft."
        ),
        evidence=(
            "The CSF includes five Functions: Identify, Protect, "
            "Detect, Respond, and Recover."
        ),
        top_k=2,
    )

    assert results == []


def test_target_tier_claim_prefers_target_tier_evidence(selector):
    """Tier 4 claims should prefer Tier 4 evidence over Tier 1 text."""

    evidence = (
        "Notional illustration of the CSF Tiers. "
        "Tier 1: Partial. Application of the organizational "
        "cybersecurity risk strategy is managed in an ad hoc manner. "
        "Tier 4: Adaptive. An organization adapts its cybersecurity "
        "practices based on lessons learned and predictive indicators."
    )

    results = selector.select(
        claim="Tier 4 is Adaptive.",
        evidence=evidence,
        top_k=2,
    )

    assert results
    assert "Tier 4" in results[0]["text"]
    assert "Adaptive" in results[0]["text"]