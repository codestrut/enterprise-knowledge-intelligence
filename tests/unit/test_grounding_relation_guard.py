from src.generation.grounding_relation_guard import (
    apply_contradiction_guard,
    content_terms,
)


def classify(claim, evidence, raw_label="contradiction"):
    return apply_contradiction_guard(
        claim=claim,
        evidence=evidence,
        raw_label=raw_label,
    )


def test_finance_fire_training_false_contradiction_is_downgraded():
    label, diagnostics = classify(
        "All new employees must complete fire-safety training.",
        "Expense claims must be submitted within 30 calendar days of the purchase.",
    )
    assert label == "neutral"
    assert diagnostics["applied"] is True


def test_procurement_annual_leave_false_contradiction_is_downgraded():
    label, diagnostics = classify(
        "Employees may carry unused annual leave into the next year.",
        "Suppliers must provide a valid tax-clearance certificate before a contract is awarded.",
    )
    assert label == "neutral"
    assert diagnostics["applied"] is True


def test_records_fire_alarm_false_contradiction_is_downgraded():
    label, diagnostics = classify(
        "The building fire alarm must be tested every month.",
        "Completed procurement records must be retained for seven years after contract closure.",
    )
    assert label == "neutral"
    assert diagnostics["applied"] is True


def test_same_subject_numeric_conflict_remains_contradiction():
    label, diagnostics = classify(
        "Eligible employees may request up to 5 paid annual leave days per calendar year.",
        "Eligible employees may request up to 20 paid annual leave days per calendar year.",
    )
    assert label == "contradiction"
    assert diagnostics["applied"] is False
    assert len(diagnostics["shared_content_terms"]) >= 2


def test_same_subject_explicit_negation_conflict_remains_contradiction():
    label, diagnostics = classify(
        "Suppliers do not need a tax-clearance certificate before a contract is awarded.",
        "Suppliers must provide a valid tax-clearance certificate before a contract is awarded.",
    )
    assert label == "contradiction"
    assert diagnostics["applied"] is False


def test_distinct_tier_number_does_not_count_as_same_subject_attribute():
    label, diagnostics = classify(
        "Tier 4 is Adaptive.",
        "Tier 1 is Partial.",
    )
    assert label == "neutral"
    assert diagnostics["applied"] is True
    assert diagnostics["shared_content_terms"] == ["tier"]


def test_entailment_is_never_changed_by_contradiction_guard():
    label, diagnostics = classify(
        "The system uses biometric authentication.",
        "The system uses role-based access control.",
        raw_label="entailment",
    )
    assert label == "entailment"
    assert diagnostics["applied"] is False


def test_neutral_is_never_changed_by_contradiction_guard():
    label, _ = classify(
        "Employees may carry annual leave into next year.",
        "Supplier certificate is required before contract award.",
        raw_label="neutral",
    )
    assert label == "neutral"


def test_content_terms_normalize_simple_plural_and_gerund_forms():
    terms = content_terms("Employees are carrying annual leaves.")
    assert "employee" in terms
    assert "carri" in terms or "carry" in terms
    assert "annual" in terms


def test_guard_diagnostics_include_shared_terms_and_reason():
    _, diagnostics = classify(
        "All new employees must complete fire-safety training.",
        "Expense claims must be submitted within 30 calendar days of the purchase.",
    )
    assert "shared_content_terms" in diagnostics
    assert diagnostics["reason"]
    assert diagnostics["minimum_shared_terms"] == 2


def test_topical_overlap_is_not_enough_to_retain_false_contradiction():
    label, diagnostics = classify(
        "Focus on actions that help communicate cybersecurity risks.",
        "The selected outcomes can be used to focus on and implement "
        "strategic decisions to improve cybersecurity postures and maintain "
        "continuity of mission-essential functions while taking priorities "
        "and available resources into account.",
    )

    assert label == "neutral"
    assert diagnostics["applied"] is True
    assert diagnostics["shared_content_terms"] == ["cybersecurity", "focus"]
    assert diagnostics["claim_term_coverage"] < diagnostics["minimum_claim_term_coverage"]
