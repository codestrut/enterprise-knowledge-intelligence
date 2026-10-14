from src.generation.lexical_support_guard import apply_near_extractive_support_guard


def classify(claim, evidence, raw="neutral", current="neutral"):
    return apply_near_extractive_support_guard(
        claim=claim,
        evidence=evidence,
        raw_label=raw,
        current_label=current,
    )


def test_near_extractive_mission_alignment_can_be_recovered():
    claim = "The actions align with the organization's mission."
    evidence = (
        "Prioritize actions for managing cybersecurity risks that align "
        "with the organization's mission, legal and regulatory requirements."
    )
    label, detail = classify(claim, evidence)
    assert label == "entailment"
    assert detail["applied"] is True
    assert detail["term_coverage"] == 1.0
    assert detail["ordered_coverage"] == 1.0


def test_near_extractive_regulatory_requirements_can_be_recovered():
    claim = "The actions align with legal and regulatory requirements."
    evidence = (
        "Identify, organize, and prioritize actions for managing cybersecurity "
        "risks that align with the organization's mission, legal and regulatory requirements."
    )
    label, detail = classify(claim, evidence)
    assert label == "entailment"
    assert detail["applied"] is True


def test_scrm_process_list_can_be_recovered_across_domains():
    claim = "Processes are identified, managed, monitored, and improved by stakeholders."
    evidence = (
        "Cyber supply chain risk management processes are identified, established, "
        "managed, monitored, and improved by organizational stakeholders."
    )
    label, detail = classify(claim, evidence)
    assert label == "entailment"
    assert detail["applied"] is True


def test_generic_overlap_does_not_promote_unrelated_claim():
    claim = "Employees may carry unused annual leave into next year."
    evidence = "Suppliers must provide a valid tax-clearance certificate before a contract is awarded."
    label, detail = classify(claim, evidence)
    assert label == "neutral"
    assert detail["applied"] is False


def test_negation_mismatch_blocks_support_recovery():
    claim = "Suppliers do not need a tax-clearance certificate before a contract is awarded."
    evidence = "Suppliers must provide a valid tax-clearance certificate before a contract is awarded."
    label, detail = classify(claim, evidence)
    assert label == "neutral"
    assert detail["applied"] is False
    assert detail["protected_markers_match"] is False


def test_modality_mismatch_blocks_support_recovery():
    claim = "Employees must complete fire-safety training."
    evidence = "Employees may complete fire-safety training."
    label, detail = classify(claim, evidence)
    assert label == "neutral"
    assert detail["applied"] is False


def test_numeric_mismatch_blocks_support_recovery():
    claim = "Eligible employees may request 5 paid annual leave days per year."
    evidence = "Eligible employees may request 20 paid annual leave days per year."
    label, detail = classify(claim, evidence)
    assert label == "neutral"
    assert detail["applied"] is False


def test_order_mismatch_blocks_support_recovery():
    claim = "The policy increases risk and reduces cost."
    evidence = "The policy reduces risk and increases cost."
    label, detail = classify(claim, evidence)
    assert label == "neutral"
    assert detail["applied"] is False


def test_different_predicted_relation_is_never_overridden():
    claim = "The system uses role-based access control."
    evidence = "The system does not use role-based access control."
    label, detail = classify(claim, evidence, raw="contradiction", current="contradiction")
    assert label == "contradiction"
    assert detail["applied"] is False


def test_minimum_claim_term_count_prevents_short_generic_matches():
    claim = "The process is secure."
    evidence = "The process is secure and the records are retained."
    label, detail = classify(claim, evidence)
    assert label == "neutral"
    assert detail["applied"] is False


def test_cross_domain_smoke_entailments_are_recoverable_when_nli_says_neutral():
    import json
    from pathlib import Path

    suite_path = (
        Path(__file__).resolve().parents[2]
        / "data/evaluation/benchmarks/cross_domain_grounding.json"
    )
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    supported_cases = [
        case for case in suite["grounding_cases"]
        if case["expected_label"] == "entailment"
    ]
    assert supported_cases, "Smoke suite must include positive support controls."

    for case in supported_cases:
        label, diagnostics = classify(case["claim"], case["evidence"])
        assert label == "entailment", case["id"]
        assert diagnostics["applied"] is True, case["id"]


def test_cross_domain_smoke_neutral_cases_are_not_promoted():
    import json
    from pathlib import Path

    suite_path = (
        Path(__file__).resolve().parents[2]
        / "data/evaluation/benchmarks/cross_domain_grounding.json"
    )
    suite = json.loads(suite_path.read_text(encoding="utf-8"))
    neutral_cases = [
        case for case in suite["grounding_cases"]
        if case["expected_label"] == "neutral"
    ]
    assert neutral_cases, "Smoke suite must include insufficient-evidence controls."

    for case in neutral_cases:
        label, diagnostics = classify(case["claim"], case["evidence"])
        assert label == "neutral", case["id"]
        assert diagnostics["applied"] is False, case["id"]


def test_document_header_numbers_do_not_block_near_extractive_support():
    claim = "The actions align with the organization's mission."
    evidence = (
        "NIST CSWP 29 The NIST Cybersecurity Framework CSF 2.0 "
        "February 26, 2024 page 2. Prioritize actions for managing "
        "cybersecurity risks that align with the organization's mission, "
        "legal and regulatory requirements."
    )
    label, diagnostics = classify(claim, evidence)
    assert label == "entailment"
    assert diagnostics["applied"] is True


def test_nist_prioritization_atoms_from_actual_diagnostic_are_recovered():
    """Exact near-extractive claims from the latest NIST diagnostic recover safely."""
    evidence = (
        "NIST CSWP 29 The NIST Cybersecurity Framework (CSF) 2.0 "
        "February 26, 2024 2 Prioritize: Identify, organize, and prioritize "
        "actions for managing cybersecurity risks that align with the organization's "
        "mission, legal and regulatory requirements, and risk management/governance expectations."
    )
    claims = [
        "The actions align with the organization's mission.",
        "The actions align with legal and regulatory requirements.",
        "The actions align with risk management/governance expectations.",
    ]

    for claim in claims:
        label, diagnostics = classify(claim, evidence)
        assert label == "entailment", claim
        assert diagnostics["applied"] is True, claim
        assert diagnostics["term_coverage"] >= 0.90, claim
        assert diagnostics["ordered_coverage"] >= 0.90, claim



def test_full_nist_prioritization_sentence_survives_one_word_paraphrase():
    """Near-verbatim evidence with a small phrase difference should be recovered."""
    claim = (
        "Identify, organize, and prioritize actions for managing cybersecurity risks "
        "in a way that aligns with the organization's mission, legal and regulatory "
        "requirements, and risk management/governance expectations."
    )
    evidence = (
        "NIST CSWP 29 The NIST Cybersecurity Framework (CSF) 2.0 February 26, 2024 2 "
        "Prioritize: Identify, organize, and prioritize actions for managing cybersecurity "
        "risks that align with the organization's mission, legal and regulatory requirements, "
        "and risk management and governance expectations."
    )

    label, diagnostics = classify(claim, evidence)

    assert label == "entailment"
    assert diagnostics["applied"] is True
    assert diagnostics["term_coverage"] >= 0.90
    assert diagnostics["ordered_coverage"] >= 0.90


def test_scrm_diagnostic_atomic_claim_is_recovered():
    claim = (
        "It ensures these are identified, managed, monitored, and improved "
        "by organizational stakeholders."
    )
    evidence = (
        "GV.OV-03: Organizational cybersecurity risk management performance "
        "is evaluated and reviewed for adjustments needed. Cybersecurity Supply "
        "Chain Risk Management (GV.SC): Cyber supply chain risk management "
        "processes are identified, established, managed, monitored, and improved "
        "by organizational stakeholders."
    )

    label, diagnostics = classify(claim, evidence)

    assert label == "entailment"
    assert diagnostics["applied"] is True



def test_ict_risk_program_excerpt_does_not_support_broader_erm_portfolio_claim():
    """Topical ICT-risk overlap must not prove a broader ERM portfolio claim."""
    claim = (
        "Organizations may use ERM to balance a portfolio of risk considerations "
        "including cybersecurity and provide executives with input on current and "
        "planned risk activities, aligning governance and risk strategies with CSF results."
    )
    evidence = (
        "Enterprise Risk Portfolio. SP 800-221A, Information and Communications Technology "
        "(ICT) Risk Outcomes: Integrating ICT Risk Management Programs with the Enterprise "
        "Risk Portfolio. An organization may also find the CSF beneficial for integrating "
        "cybersecurity risk management with individual ICT risk management programs, such as "
        "cybersecurity risk management and assessment. The CSF can be integrated with "
        "established cybersecurity risk management and assessment programs, such as SP 800-37 "
        "and SP 800-30."
    )

    label, diagnostics = classify(claim, evidence)

    assert label == "neutral"
    assert diagnostics["applied"] is False


def test_looser_erm_paraphrase_is_not_promoted_by_near_extractive_guard():
    claim = "Governance and risk strategies are aligned with CSF results."
    evidence = (
        "Executives receive significant input about current and planned risk "
        "activities as they integrate governance and risk strategies with results "
        "from previous uses of the CSF."
    )

    label, diagnostics = classify(claim, evidence)

    assert label == "neutral"
    assert diagnostics["applied"] is False


def test_scrm_definition_is_recovered_with_restricted_near_extractive_fallback():
    claim = (
        "Cybersecurity supply chain risk management (C-SCRM) is a systematic "
        "process for managing exposure to cybersecurity risk throughout supply chains."
    )
    evidence = (
        "Cybersecurity SCRM (C-SCRM) is a systematic process for managing exposure "
        "to cybersecurity risk throughout supply chains and developing appropriate "
        "response strategies, policies, processes, and procedures."
    )

    label, diagnostics = classify(claim, evidence)

    assert label == "entailment"
    assert diagnostics["applied"] is True
    assert diagnostics["relaxed_order_recovery_applied"] is True
    assert diagnostics["term_coverage"] >= 0.90
    assert diagnostics["ordered_coverage"] >= 0.70
    assert diagnostics["protected_markers_match"] is True


def test_restricted_near_extractive_fallback_does_not_accept_reversed_predicates():
    claim = "The policy increases risk and reduces cost."
    evidence = "The policy reduces risk and increases cost."

    label, diagnostics = classify(claim, evidence)

    assert label == "neutral"
    assert diagnostics["applied"] is False
    assert diagnostics["relaxed_order_recovery_applied"] is False
