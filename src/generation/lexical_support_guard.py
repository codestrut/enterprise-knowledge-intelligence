"""Conservative recovery for near-extractive evidence the NLI model calls neutral.

This guard is intentionally narrower than a semantic entailment model. It only
promotes a neutral prediction when nearly all meaningful claim terms occur in
the evidence in the same order and safety-critical markers match. It must not
be used to infer support from broad topical similarity alone.
"""
from __future__ import annotations

import re
from typing import Any

from src.generation.grounding_relation_guard import (
    _CONTENT_STOPWORDS,
    _normalise_token,
    content_terms,
)

# Differences in these markers may change the proposition even when most
# content words overlap (e.g. may vs must, not vs allowed, current vs target).
_PROTECTED_WORDS = frozenset(
    """
    all each every some any none only not no never neither nor without unless
    except must may should shall will can cannot could might required requires
    require mandatory optional prohibited forbidden disallowed allowed permitted
    before after within during until since current target previous prior future
    first last more less minimum maximum exactly approximately at least most up
    between increase decrease higher lower greater fewer fewer than equal same
    """.split()
)
_PROTECTED_PHRASES = (
    "no more than",
    "no less than",
    "at least",
    "at most",
    "up to",
    "more than",
    "less than",
    "greater than",
    "fewer than",
)
_NUMBER_PATTERN = re.compile(r"(?<![a-z])\d+(?:[.,]\d+)?\s*%?", re.IGNORECASE)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)


def _ordered_content_terms(text: str) -> list[str]:
    """Return the normalized content terms in original order."""
    result: list[str] = []
    for raw in _TOKEN_PATTERN.findall(text.casefold()):
        token = _normalise_token(raw)
        if token and token not in _CONTENT_STOPWORDS and len(token) >= 2:
            result.append(token)
    return result


def _protected_markers(text: str) -> set[str]:
    lowered = " ".join(_TOKEN_PATTERN.findall(text.casefold()))
    markers = {token for token in _TOKEN_PATTERN.findall(lowered) if token in _PROTECTED_WORDS}
    markers.update(
        f"phrase:{phrase}"
        for phrase in _PROTECTED_PHRASES
        if re.search(rf"\b{re.escape(phrase)}\b", lowered)
    )
    # Scan the original string to preserve decimal values such as 2.0.
    markers.update(
        f"number:{number.replace(' ', '')}"
        for number in _NUMBER_PATTERN.findall(text.casefold())
    )
    return markers


def _protected_markers_compatible(claim_markers: set[str], evidence_markers: set[str]) -> bool:
    """Require equal semantic markers, but allow incidental numbers in evidence.

    Document headers, page IDs and control identifiers often introduce numbers
    that are not part of the proposition. If the claim specifies numbers, they
    must be present in evidence; extra evidence numbers are permitted because
    nearby chunks may include unrelated metadata or additional facts.
    """
    claim_words = {marker for marker in claim_markers if not marker.startswith("number:")}
    evidence_words = {marker for marker in evidence_markers if not marker.startswith("number:")}
    claim_numbers = {marker for marker in claim_markers if marker.startswith("number:")}
    evidence_numbers = {marker for marker in evidence_markers if marker.startswith("number:")}
    return claim_words == evidence_words and claim_numbers.issubset(evidence_numbers)


def _ordered_coverage(claim_terms: list[str], evidence_terms: list[str]) -> float:
    """Measure claim-term order coverage using longest common subsequence.

    A greedy scan can incorrectly consume the rest of the evidence when one
    claim token is absent (for example, "in a way that aligns" vs "that align").
    LCS preserves the ordering requirement while allowing insertions, headers,
    and small paraphrase differences. The denominator remains the claim length,
    so evidence that omits too much of the proposition does not pass.
    """
    if not claim_terms:
        return 0.0

    # One-row dynamic programming: O(len(claim_terms) * len(evidence_terms))
    # time and O(len(evidence_terms)) additional memory. Claims/evidence chunks
    # are bounded, so this remains small in the grounding evaluation path.
    previous = [0] * (len(evidence_terms) + 1)
    for claim_term in claim_terms:
        current = [0] * (len(evidence_terms) + 1)
        for index, evidence_term in enumerate(evidence_terms, start=1):
            if claim_term == evidence_term:
                current[index] = previous[index - 1] + 1
            else:
                current[index] = max(previous[index], current[index - 1])
        previous = current

    return previous[-1] / len(claim_terms)


def apply_near_extractive_support_guard(
    *,
    claim: str,
    evidence: str,
    current_label: str,
    raw_label: str,
    minimum_claim_terms: int = 3,
    minimum_term_coverage: float = 0.90,
    minimum_ordered_coverage: float = 0.90,
    minimum_relaxed_ordered_coverage: float = 0.70,
    minimum_relaxed_claim_terms: int = 8,
) -> tuple[str, dict[str, Any]]:
    """Promote only high-coverage, order-preserving neutral pairs to entailment.

    This is a deterministic near-extractive support rule, not a replacement
    for NLI. It runs only when both the raw and currently effective labels are
    neutral. It refuses promotion when polarity/modality/quantifier/time or
    numeric markers differ, and requires strong content-term and order
    coverage. All thresholds are explicit and may be evaluated on held-out
    domains; they must not be tuned only on a single corpus.
    """
    claim_sequence = _ordered_content_terms(claim)
    evidence_sequence = _ordered_content_terms(evidence)
    claim_set = set(claim_sequence)
    evidence_set = set(evidence_sequence)
    shared = sorted(claim_set & evidence_set)
    term_coverage = len(shared) / len(claim_set) if claim_set else 0.0
    ordered_coverage = _ordered_coverage(claim_sequence, evidence_sequence)
    claim_markers = sorted(_protected_markers(claim))
    evidence_markers = sorted(_protected_markers(evidence))
    markers_match = _protected_markers_compatible(
        set(claim_markers), set(evidence_markers)
    )

    diagnostics: dict[str, Any] = {
        "applied": False,
        "reason": None,
        "minimum_claim_terms": minimum_claim_terms,
        "minimum_term_coverage": minimum_term_coverage,
        "minimum_ordered_coverage": minimum_ordered_coverage,
        "minimum_relaxed_ordered_coverage": minimum_relaxed_ordered_coverage,
        "minimum_relaxed_claim_terms": minimum_relaxed_claim_terms,
        "relaxed_order_recovery_applied": False,
        "claim_content_terms": sorted(claim_set),
        "shared_content_terms": shared,
        "claim_content_term_count": len(claim_set),
        "term_coverage": term_coverage,
        "ordered_coverage": ordered_coverage,
        "claim_protected_markers": claim_markers,
        "evidence_protected_markers": evidence_markers,
        "protected_markers_match": markers_match,
    }

    if current_label != "neutral" or raw_label != "neutral":
        diagnostics["reason"] = "Support recovery applies only to raw neutral predictions."
        return current_label, diagnostics

    if len(claim_set) < minimum_claim_terms:
        diagnostics["reason"] = "Too few meaningful claim terms for a safe lexical support decision."
        return current_label, diagnostics

    if not markers_match:
        diagnostics["reason"] = "Protected polarity, modality, quantity, time, or numeric markers differ."
        return current_label, diagnostics

    if term_coverage < minimum_term_coverage:
        diagnostics["reason"] = "Meaningful claim-term coverage is below the near-extractive threshold."
        return current_label, diagnostics

    if ordered_coverage < minimum_ordered_coverage:
        # A narrow fallback for long, near-extractive statements where a small
        # wording/abbreviation difference lowers token-order coverage (e.g. an
        # expanded term versus its acronym). Keep the main 90% order gate. The
        # fallback additionally requires >=90% content-term coverage, a long
        # claim, and exact agreement on protected polarity/modality/quantity
        # markers. Reversed predicate/control examples must remain neutral.
        relaxed_near_extract = (
            len(claim_set) >= minimum_relaxed_claim_terms
            and term_coverage >= minimum_term_coverage
            and ordered_coverage >= minimum_relaxed_ordered_coverage
            and markers_match
        )
        if not relaxed_near_extract:
            diagnostics["reason"] = (
                "Claim terms do not occur in sufficiently similar order in the evidence."
            )
            return current_label, diagnostics
        diagnostics["relaxed_order_recovery_applied"] = True

    diagnostics["applied"] = True
    if diagnostics["relaxed_order_recovery_applied"]:
        diagnostics["reason"] = (
            "Promoted raw-neutral claim using a restricted near-extractive fallback: "
            "high content-term coverage, adequate ordered coverage, a long claim, "
            "and matching protected markers."
        )
    else:
        diagnostics["reason"] = (
            "Promoted neutral to entailment using conservative near-extractive "
            "support: high ordered content-term coverage and matching protected markers."
        )
    return "entailment", diagnostics
