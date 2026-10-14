"""Unit tests for the bounded grounding-repair policy."""

from src.generation.answer_repair import (
    ABSTENTION_TEXT,
    answer_passes_grounding,
    build_grounded_subset_answer,
    build_repair_prompt,
    is_explicit_abstention,
    summarize_grounding_issues,
)


def test_fully_grounded_cited_answer_passes():
    grounding = [{"claim": "Policy applies.", "status": "grounded"}]
    assert answer_passes_grounding("Policy applies. [Source 1]", grounding, [])


def test_unsupported_claim_fails_grounding_gate():
    grounding = [{"claim": "Policy applies.", "status": "unsupported"}]
    assert not answer_passes_grounding("Policy applies. [Source 1]", grounding, [])


def test_invalid_citation_fails_grounding_gate():
    grounding = [{"claim": "Policy applies.", "status": "grounded"}]
    assert not answer_passes_grounding(
        "Policy applies. [Source 99]", grounding, [99]
    )


def test_empty_grounding_does_not_pass_as_factual_answer():
    assert not answer_passes_grounding("An uncited factual answer.", [], [])


def test_explicit_abstention_passes_without_citations():
    assert is_explicit_abstention(ABSTENTION_TEXT)
    assert answer_passes_grounding(ABSTENTION_TEXT, [], [])


def test_issue_summary_includes_only_flagged_claims_and_invalid_citations():
    issues = summarize_grounding_issues(
        [
            {"claim": "Supported claim.", "status": "grounded"},
            {"claim": "Unsupported claim.", "status": "unsupported"},
        ],
        [99],
    )
    assert len(issues) == 2
    assert issues[0]["claim"] == "Unsupported claim."
    assert issues[1]["status"] == "invalid_citation"


def test_repair_prompt_treats_draft_as_untrusted_and_requires_abstention():
    prompt = build_repair_prompt(
        query="What is the policy?",
        context="[Source 1] The policy requires annual review.",
        draft_answer="The policy requires monthly review. [Source 1]",
        issues=[{"claim": "monthly review", "status": "contradicted"}],
    )
    assert "DRAFT ANSWER TO CORRECT (not evidence)" in prompt
    assert "Do not add new facts" in prompt
    assert ABSTENTION_TEXT in prompt


def test_explicit_abstention_with_invalid_citation_does_not_pass():
    assert not answer_passes_grounding(ABSTENTION_TEXT + " [Source 99]", [], [99])


def test_abstention_phrase_mixed_with_claim_is_not_safe_abstention():
    mixed = ABSTENTION_TEXT + " The policy requires monthly review. [Source 1]"
    assert not is_explicit_abstention(mixed)
    assert not answer_passes_grounding(mixed, [], [])


def test_repair_prompt_explicitly_preserves_agent_and_direction():
    prompt = build_repair_prompt(
        query="How are risks integrated?",
        context="[Source 1] Executives receive significant input about risk activities.",
        draft_answer="Executives provide input about risk activities. [Source 1]",
        issues=[{"claim": "Executives provide input.", "status": "unsupported"}],
    )
    assert "keep the same subject/agent, action, recipient/object, and direction" in prompt
    assert "do not write 'executives provide input'" in prompt
    assert "Do not add interpretive bridge claims such as 'this supports'" in prompt
    assert "retain only the shortest directly supported answer" in prompt


def test_grounded_subset_uses_only_grounded_atoms_and_known_source_numbers():
    grounding = [{
        "claim": "A compound sentence that failed overall.",
        "status": "unsupported",
        "atomic_claims": [
            {
                "claim": "The CSF translates cybersecurity risk terminology into general risk management language.",
                "status": "grounded",
                "sources": [{"source_number": 3, "label": "entailment", "conflict_detected": False}],
            },
            {
                "claim": "Executives provide input about risk activities.",
                "status": "unsupported",
                "sources": [{"source_number": 3, "label": "neutral", "conflict_detected": False}],
            },
        ],
    }]

    answer = build_grounded_subset_answer(grounding)

    assert answer == (
        "- The CSF translates cybersecurity risk terminology into general risk management language. [Source 3]"
    )
    assert "Executives provide input" not in answer


def test_grounded_subset_skips_conflicted_or_uncited_atoms():
    grounding = [{
        "claim": "Top-level claim.",
        "status": "unsupported",
        "atomic_claims": [
            {
                "claim": "A conflicted claim.",
                "status": "grounded",
                "sources": [{"source_number": 1, "label": "entailment", "conflict_detected": True}],
            },
            {
                "claim": "A claim without sources.",
                "status": "grounded",
                "sources": [],
            },
        ],
    }]
    assert build_grounded_subset_answer(grounding) == ""
