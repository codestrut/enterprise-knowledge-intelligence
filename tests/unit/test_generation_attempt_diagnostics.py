from src.generation.answer_repair import summarize_answer_attempt


def test_diagnostics_identify_a_clean_grounded_answer_without_returning_text():
    result = summarize_answer_attempt(
        "An Organizational Profile describes cybersecurity posture. [Source 1]",
        [{"status": "grounded", "claim": "private content must not leak"}],
        [],
    )

    assert result["empty_answer"] is False
    assert result["explicit_abstention"] is False
    assert result["citation_marker_count"] == 1
    assert result["grounding_claim_count"] == 1
    assert result["grounding_status_counts"] == {"grounded": 1}
    assert result["invalid_citation_count"] == 0
    assert result["passes_grounding"] is True
    assert "answer" not in result


def test_diagnostics_identify_repair_abstention_and_failed_verification():
    result = summarize_answer_attempt(
        "I don't have sufficient evidence in the available knowledge base to answer that question.",
        [],
        [],
    )

    assert result["explicit_abstention"] is True
    assert result["citation_marker_count"] == 0
    assert result["grounding_claim_count"] == 0
    assert result["grounding_status_counts"] == {}
    assert result["passes_grounding"] is True


def test_diagnostics_distinguish_invalid_citations_and_unsupported_claims():
    result = summarize_answer_attempt(
        "A claim. [Source 4]",
        [{"status": "unsupported"}],
        ["[Source 4]"],
    )

    assert result["grounding_status_counts"] == {"unsupported": 1}
    assert result["invalid_citation_count"] == 1
    assert result["passes_grounding"] is False


def test_grounding_details_surface_unsupported_claim_and_source_pair():
    from src.generation.answer_repair import summarize_grounding_details

    details = summarize_grounding_details([
        {
            "claim": "Risks are integrated quarterly.",
            "status": "unsupported",
            "atomic_claims": [
                {
                    "claim": "Risks are integrated quarterly.",
                    "status": "unsupported",
                    "sources": [
                        {
                            "source_number": 3,
                            "label": "neutral",
                            "conflict_detected": False,
                            "evidence": [
                                {
                                    "label": "neutral",
                                    "raw_label": "neutral",
                                    "evidence": "The framework requires integration with enterprise risk management.",
                                    "probabilities": {"contradiction": 0.01, "entailment": 0.1, "neutral": 0.89},
                                    "relation_guard": {"applied": False, "reason": "No guard needed."},
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ])

    assert details[0]["status"] == "unsupported"
    assert details[0]["atomic_claims"][0]["claim"] == "Risks are integrated quarterly."
    evidence = details[0]["atomic_claims"][0]["sources"][0]["evidence"][0]
    assert evidence["raw_label"] == "neutral"
    assert "enterprise risk management" in evidence["evidence"]
