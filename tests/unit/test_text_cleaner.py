"""Regression tests for conservative PDF text normalization."""

from src.ingestion.text_cleaner import clean_text


def test_normalizes_known_split_nist_sp_800_53_identifier():
    assert clean_text("controls from SP 800-5 3, Security and Privacy Controls") == (
        "controls from SP 800-53, Security and Privacy Controls"
    )
    assert clean_text("controls from SP 800- 5 3") == "controls from SP 800-53"


def test_does_not_join_arbitrary_number_sequences():
    text = "SP 800-537 and unrelated digits 12 34"
    assert clean_text(text) == text
