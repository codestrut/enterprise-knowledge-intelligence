"""Conflict-cue requirement for NLI contradictions (GV.SC-02 regression)."""

import json
from pathlib import Path

from src.generation.grounding_relation_guard import (
    apply_contradiction_guard,
    conflict_cues,
)

SUITE = (
    Path(__file__).resolve().parents[2]
    / "data/evaluation/benchmarks/cross_domain_grounding.json"
)

GV_SC_02_CLAIM = (
    "The CSF also covers cybersecurity roles and responsibilities for external parties."
)
GV_SC_02_EVIDENCE = (
    "Cybersecurity roles and responsibilities for suppliers, customers, and "
    "partners are established, communicated, understood, and enforced."
)


def guard(claim, evidence, **kwargs):
    return apply_contradiction_guard(
        claim=claim, evidence=evidence, raw_label="contradiction", **kwargs
    )


def test_gv_sc_02_false_contradiction_is_downgraded_to_neutral():
    # Observed live: raw contradiction probability 0.977, claim-term coverage
    # 3/7 = 0.429, which the overlap-only guard retained.
    label, diagnostics = guard(GV_SC_02_CLAIM, GV_SC_02_EVIDENCE)
    assert label == "neutral"
    assert diagnostics["applied"] is True
    assert diagnostics["conflict_cues"] == []
    assert "conflict cue" in diagnostics["reason"]


def test_overlap_only_behaviour_is_available_for_comparison():
    label, diagnostics = guard(
        GV_SC_02_CLAIM, GV_SC_02_EVIDENCE, require_conflict_cue=False
    )
    assert label == "contradiction"
    assert diagnostics["applied"] is False
    assert diagnostics["conflict_cue_required"] is False


def test_every_labelled_contradiction_in_the_smoke_suite_is_retained():
    cases = json.loads(SUITE.read_text())["grounding_cases"]
    contradictions = [c for c in cases if c["expected_label"] == "contradiction"]
    assert len(contradictions) >= 6
    for case in contradictions:
        label, diagnostics = guard(case["claim"], case["evidence"])
        assert label == "contradiction", case["id"]
        assert diagnostics["conflict_cues"], case["id"]


def test_negation_mismatch_is_a_cue():
    assert "negation_mismatch" in conflict_cues(
        "Suppliers do not need a certificate.",
        "Suppliers must provide a certificate.",
    )


def test_negation_on_both_sides_is_not_a_cue():
    assert "negation_mismatch" not in conflict_cues(
        "Staff must not share passwords.",
        "Staff shall not disclose passwords.",
    )


def test_modality_mismatch_is_a_cue():
    assert "modality_mismatch" in conflict_cues(
        "Staff must attend training.", "Staff may attend training."
    )


def test_spelled_out_numbers_are_compared():
    assert "number_mismatch" in conflict_cues(
        "Records are retained for three years.",
        "Records are retained for seven years.",
    )


def test_numbers_with_attached_units_are_compared():
    assert "number_mismatch" in conflict_cues(
        "The gateway uses a 24V adapter.", "The gateway uses a 12V adapter."
    )


def test_evidence_without_numbers_is_silent_not_conflicting():
    assert "number_mismatch" not in conflict_cues(
        "Employees may take up to 5 days.", "Employees may take leave."
    )


def test_disjoint_quantifiers_are_a_cue():
    assert "quantifier_mismatch" in conflict_cues(
        "All staff must attend.", "Only managers must attend."
    )


def test_antonyms_are_a_cue():
    assert "antonym:increase/decrease" in conflict_cues(
        "Incident volume will increase.", "Incident volume will decrease."
    )


def test_same_topic_pair_without_cue_is_downgraded():
    label, _ = guard(
        "The program covers incident response roles for contractors.",
        "Incident response roles for vendors and partners are defined.",
    )
    assert label == "neutral"


def test_non_contradictions_are_never_changed():
    for raw in ("entailment", "neutral"):
        label, diagnostics = apply_contradiction_guard(
            claim=GV_SC_02_CLAIM, evidence=GV_SC_02_EVIDENCE, raw_label=raw
        )
        assert label == raw
        assert diagnostics["applied"] is False


def test_downgrade_never_produces_a_supporting_label():
    label, _ = guard(GV_SC_02_CLAIM, GV_SC_02_EVIDENCE)
    assert label != "entailment"
