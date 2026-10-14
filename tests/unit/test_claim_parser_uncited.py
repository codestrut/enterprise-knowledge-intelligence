"""Uncited sentences must be returned, not silently dropped."""

from src.generation.claim_parser import parse_claims


def _shape(answer):
    return [
        (item["claim"], item["source_numbers"], item.get("uncited", False))
        for item in parse_claims(answer)
    ]


def test_uncited_sentence_between_citation_groups_is_returned():
    answer = (
        "Govern sets strategy. [Source 1] "
        "Roles are assigned by leadership. "
        "Identify covers assets. [Source 2]"
    )
    assert _shape(answer) == [
        ("Govern sets strategy.", [1], False),
        ("Roles are assigned by leadership.", [], True),
        ("Identify covers assets.", [2], False),
    ]


def test_uncited_bullet_between_cited_bullets_is_returned():
    answer = "- A. [Source 1]\n- B has no citation\n- C. [Source 2]"
    assert _shape(answer) == [
        ("A.", [1], False),
        ("B has no citation", [], True),
        ("C.", [2], False),
    ]


def test_uncited_text_after_last_group_is_returned():
    answer = "Govern sets strategy. [Source 1] Protect limits all access."
    assert _shape(answer) == [
        ("Govern sets strategy.", [1], False),
        ("Protect limits all access.", [], True),
    ]


def test_answer_without_any_citation_returns_every_sentence_uncited():
    assert _shape("Govern sets strategy. Identify covers assets.") == [
        ("Govern sets strategy.", [], True),
        ("Identify covers assets.", [], True),
    ]


def test_structural_lead_in_is_never_returned_as_uncited():
    answer = "The following points include:\n- A is true. [Source 1]"
    assert all("following points" not in item["claim"] for item in parse_claims(answer))


def test_citation_metadata_marker_is_not_an_uncited_claim():
    answer = "Tier 2: Risk Informed [Source 1].\n[Citations: Source 1][Source 2]"
    assert [item["claim"] for item in parse_claims(answer)] == ["Tier 2: Risk Informed"]


def test_cited_records_have_no_uncited_flag():
    claims = parse_claims("Supported fact [Source 1].")
    assert claims == [{"claim": "Supported fact", "source_numbers": [1]}]
