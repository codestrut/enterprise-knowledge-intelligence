"""Tests for claim parsing and citation association."""

from src.generation.claim_parser import parse_claims


def test_single_final_citation_applies_to_multiple_sentences():
    answer = (
        "An Organizational Profile describes an organization's posture. "
        "It can include a Current Profile or a Target Profile. "
        "[Source 1][Source 5]"
    )
    claims = parse_claims(answer)
    assert [item["claim"] for item in claims] == [
        "An Organizational Profile describes an organization's posture.",
        "It can include a Current Profile or a Target Profile.",
    ]
    assert all(item["source_numbers"] == [1, 5] for item in claims)


def test_inline_citations_map_to_their_own_sentences():
    answer = "First fact is supported. [Source 1] Second fact is supported. [Source 2]"
    claims = parse_claims(answer)
    assert [item["source_numbers"] for item in claims] == [[1], [2]]
    assert [item["claim"] for item in claims] == [
        "First fact is supported.",
        "Second fact is supported.",
    ]


def test_uncited_sentence_between_cited_sentences_is_not_attributed():
    answer = "Supported fact [Source 1]. Uncited assertion. Later fact [Source 2]."
    claims = parse_claims(answer)
    assert [item["claim"] for item in claims] == [
        "Supported fact",
        "Uncited assertion.",
        "Later fact",
    ]
    # The uncited sentence is evaluated as uncited; it never borrows a citation.
    assert [item["source_numbers"] for item in claims] == [[1], [], [2]]
    assert [item.get("uncited", False) for item in claims] == [False, True, False]


def test_bullets_with_multiple_sentences_share_their_bullet_citation():
    answer = (
        "- First bullet statement. Additional detail. [Source 1]\n"
        "- Second bullet statement. More detail. [Source 2]"
    )
    claims = parse_claims(answer)
    assert [item["claim"] for item in claims] == [
        "First bullet statement.",
        "Additional detail.",
        "Second bullet statement.",
        "More detail.",
    ]
    assert [item["source_numbers"] for item in claims] == [[1], [1], [2], [2]]


def test_paragraph_citations_are_scoped_independently():
    answer = (
        "First paragraph has two sentences. Second sentence too. [Source 1]\n\n"
        "Second paragraph has two sentences. Another sentence. [Source 2]"
    )
    claims = parse_claims(answer)
    assert [item["source_numbers"] for item in claims] == [[1], [1], [2], [2]]


def test_uncited_answer_returns_uncited_claims():
    assert parse_claims("An organization manages cybersecurity risk.") == [
        {
            "claim": "An organization manages cybersecurity risk.",
            "source_numbers": [],
            "uncited": True,
        }
    ]


def test_empty_answer_returns_no_claims():
    assert parse_claims("") == []
    assert parse_claims(None) == []


def test_duplicate_sources_are_deduplicated_in_order():
    claims = parse_claims("Supported fact [Source 2][Source 1][Source 2].")
    assert claims == [{"claim": "Supported fact", "source_numbers": [2, 1]}]


def test_trailing_uncited_text_is_not_assigned_a_citation():
    claims = parse_claims("Supported fact [Source 1]. Uncited trailing assertion.")
    assert claims == [
        {"claim": "Supported fact", "source_numbers": [1]},
        {
            "claim": "Uncited trailing assertion.",
            "source_numbers": [],
            "uncited": True,
        },
    ]


def test_malformed_citation_summary_marker_is_not_a_claim():
    answer = (
        "Tier 2: Risk Informed [Source 1].\n"
        "[Citations: Source 1][Source 2]"
    )
    claims = parse_claims(answer)
    assert all("Citations:" not in item["claim"] for item in claims)
    assert claims[0]["claim"] == "Tier 2: Risk Informed"
    assert claims[0]["source_numbers"] == [1, 2]


def test_anaphoric_sentence_carries_full_prior_answer_context():
    answer = (
        "NIST CSF 2.0 defines Roles, Responsibilities, and Authorities. "
        "It states that organizational leadership is accountable for cybersecurity risk. "
        "It also covers cybersecurity roles for suppliers and partners. [Source 1]"
    )
    claims = parse_claims(answer)
    assert len(claims) == 3
    assert claims[2]["claim"] == (
        "It also covers cybersecurity roles for suppliers and partners."
    )
    assert claims[2]["context"] == (
        "NIST CSF 2.0 defines Roles, Responsibilities, and Authorities. "
        "It states that organizational leadership is accountable for cybersecurity risk."
    )


def test_adjacent_citation_groups_merge_into_previous_claim():
    claims = parse_claims(
        "Tier 2: Risk Informed [Source 1].\n"
        "[Citations: Source 1][Source 2]"
    )
    assert claims == [
        {"claim": "Tier 2: Risk Informed", "source_numbers": [1, 2]}
    ]


def test_anaphoric_context_keeps_referent_across_inline_citation_groups():
    answer = (
        "NIST CSF 2.0 defines Roles, Responsibilities, and Authorities. [Source 1] "
        "It states that organizational leadership is accountable for cybersecurity risk. [Source 1] "
        "It also covers cybersecurity roles for suppliers and partners. [Source 2]"
    )
    claims = parse_claims(answer)
    assert len(claims) == 3
    assert claims[2]["context"] == (
        "NIST CSF 2.0 defines Roles, Responsibilities, and Authorities. "
        "It states that organizational leadership is accountable for cybersecurity risk."
    )


def test_structural_list_preamble_is_not_counted_as_a_claim():
    answer = (
        "Specific points include:\n"
        "- GV.RR-04: Cybersecurity is included in human resources.\n"
        "- GV.SC-02: Supplier, customer, and partner roles are coordinated. "
        "[Source 1]"
    )
    claims = parse_claims(answer)
    assert [item["claim"] for item in claims] == [
        "GV.RR-04: Cybersecurity is included in human resources.",
        "GV.SC-02: Supplier, customer, and partner roles are coordinated.",
    ]
    assert all(item["claim"] != "Specific points include:" for item in claims)
