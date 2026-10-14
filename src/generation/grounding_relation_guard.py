"""Conservative, corpus-agnostic guard for false NLI contradictions.

NLI models occasionally label unrelated premise/hypothesis pairs as
contradiction with high confidence. This guard does not prove contradiction.
It only downgrades a contradiction to neutral when the claim and evidence have
insufficient normalized content-term overlap. Entailment and neutral labels are
left unchanged. The rule is deliberately domain-independent and configurable.
"""

from __future__ import annotations

import re
from typing import Any

# High-frequency grammatical and boilerplate terms are excluded only when
# measuring topical overlap. Relationship/value terms such as "required",
# "prohibited", "allowed", "increase", "decrease", and numeric values remain.
_CONTENT_STOPWORDS = frozenset(
    """
    a an the and or but if then else when while where which who whom whose
    this that these those it its they them their we our you your he she his her
    i me my mine ours yours theirs as at by for from in into of on onto out over
    through to under up with within without about above below between during
    before after across around per via is are am was were be been being do does did
    have has had having can could may might must shall should will would ought
    not no nor never neither either also only just even very more most less least
    than so such there here all any each every both some many much few several
    other another same different own once twice first second third next previous
    new old current target based according including include includes included
    use uses used using make makes made get gets got provide provides provided
    need needs needed ensure ensures ensuring
    state states stated say says said describe describes described description
    organization organizational organizations document documents information
    content context claim evidence passage text source answer answerable
    system systems process processes procedure procedures policy policies rule
    rules
    """.split()
)


def _normalise_token(token: str) -> str:
    """Apply small deterministic morphology normalization without NLP models."""
    token = token.casefold()
    if len(token) > 5 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 6 and token.endswith("sses"):
        return token[:-2]
    if len(token) > 5 and token.endswith(("ches", "shes", "xes", "zes")):
        return token[:-2]
    if len(token) > 5 and token.endswith("ing"):
        stem = token[:-3]
        if len(stem) > 2 and stem[-1] == stem[-2]:
            stem = stem[:-1]
        return stem
    if len(token) > 4 and token.endswith("ied"):
        return token[:-3] + "y"
    if len(token) > 4 and token.endswith("ed"):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def content_terms(text: str) -> set[str]:
    """Extract normalized topical terms, excluding common function words."""
    terms = set()
    for raw in re.findall(r"[a-z0-9]+", text.casefold()):
        token = _normalise_token(raw)
        if not token or token in _CONTENT_STOPWORDS or len(token) < 2:
            continue
        terms.add(token)
    return terms


# --- Conflict cues -----------------------------------------------------------
# Topical overlap shows that two statements are about the same thing, not that
# they disagree. A raw NLI contradiction is therefore kept only when the pair
# also shows a detectable *cue* that the propositions differ: opposite polarity,
# different modality, a different numeric value, disjoint quantifiers, or an
# antonym pair. Downgrading a contradiction to neutral can never make an
# ungrounded claim grounded; it only changes "contradicted" to "unsupported".

_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_NEGATION_WORDS = frozenset(
    "not no never cannot without neither nor none prohibited forbidden "
    "disallowed unable".split()
)
_NEGATION_CONTRACTION = re.compile(r"n't\b")
_MODALITY = {
    "obligation": frozenset(
        "must shall required requires require mandatory obligatory".split()
    ),
    "permission": frozenset("may might can allowed permitted optional".split()),
}
_QUANTIFIERS = frozenset(
    "all every each always only none unlimited any some most few".split()
)
_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}
_ANTONYM_PAIRS = (
    ("increase", "decrease"), ("increased", "decreased"),
    ("higher", "lower"), ("more", "fewer"), ("more", "less"),
    ("before", "after"), ("internal", "external"), ("inbound", "outbound"),
    ("public", "private"), ("enable", "disable"), ("enabled", "disabled"),
    ("include", "exclude"), ("included", "excluded"),
    ("minimum", "maximum"), ("open", "closed"), ("encrypted", "unencrypted"),
)


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.casefold())


def _is_negated(text: str, tokens: list[str]) -> bool:
    return bool(_NEGATION_CONTRACTION.search(text.casefold())) or any(
        token in _NEGATION_WORDS for token in tokens
    )


_DIGIT_VALUE = re.compile(r"(?<![a-z0-9])\d+(?:\.\d+)?")


def _numbers(text: str, tokens: list[str]) -> set[str]:
    """Numeric values as digits (units may be attached, e.g. 24V) or words."""
    values = {
        match.lstrip("0") or "0" if "." not in match else match
        for match in _DIGIT_VALUE.findall(text.casefold())
    }
    values.update(_NUMBER_WORDS[t] for t in tokens if t in _NUMBER_WORDS)
    return values


def _modalities(tokens: list[str]) -> set[str]:
    return {
        name
        for name, words in _MODALITY.items()
        if any(token in words for token in tokens)
    }


def conflict_cues(claim: str, evidence: str) -> list[str]:
    """Return the cues showing that claim and evidence may truly disagree.

    An empty list means the pair has no detectable conflict cue. The cue set is
    deliberately small and explainable; it is not a contradiction detector.
    """
    claim_tokens, evidence_tokens = _tokens(claim), _tokens(evidence)
    cues: list[str] = []

    if _is_negated(claim, claim_tokens) != _is_negated(evidence, evidence_tokens):
        cues.append("negation_mismatch")

    claim_modal, evidence_modal = _modalities(claim_tokens), _modalities(evidence_tokens)
    if claim_modal and evidence_modal and claim_modal.isdisjoint(evidence_modal):
        cues.append("modality_mismatch")

    claim_numbers = _numbers(claim, claim_tokens)
    evidence_numbers = _numbers(evidence, evidence_tokens)
    # Evidence that states no number is silent, not conflicting.
    if claim_numbers and evidence_numbers and (claim_numbers - evidence_numbers):
        cues.append("number_mismatch")
    if ("unlimited" in claim_tokens and evidence_numbers) or (
        "unlimited" in evidence_tokens and claim_numbers
    ):
        cues.append("unlimited_vs_number")

    claim_quant = {t for t in claim_tokens if t in _QUANTIFIERS}
    evidence_quant = {t for t in evidence_tokens if t in _QUANTIFIERS}
    if claim_quant and evidence_quant and claim_quant.isdisjoint(evidence_quant):
        cues.append("quantifier_mismatch")

    claim_set, evidence_set = set(claim_tokens), set(evidence_tokens)
    for left, right in _ANTONYM_PAIRS:
        if (left in claim_set and right in evidence_set) or (
            right in claim_set and left in evidence_set
        ):
            cues.append(f"antonym:{left}/{right}")

    return cues


def apply_contradiction_guard(
    *,
    claim: str,
    evidence: str,
    raw_label: str,
    minimum_shared_terms: int = 2,
    minimum_claim_term_coverage: float = 0.40,
    require_conflict_cue: bool = True,
) -> tuple[str, dict[str, Any]]:
    """Return an effective label plus audit diagnostics.

    Only raw contradictions are eligible for downgrade. A contradiction must
    share at least a minimum number of normalized content terms and enough of
    the claim's content terms. This avoids retaining contradictions based only
    on broad topical overlap. Some valid heavily paraphrased contradictions may
    be downgraded, so the defaults must be evaluated against held-out examples.
    """
    claim_terms = content_terms(claim)
    evidence_terms = content_terms(evidence)
    shared_terms = sorted(claim_terms.intersection(evidence_terms))

    diagnostics: dict[str, Any] = {
        "applied": False,
        "reason": None,
        "minimum_shared_terms": minimum_shared_terms,
        "minimum_claim_term_coverage": minimum_claim_term_coverage,
        "claim_term_coverage": (
            len(shared_terms) / len(claim_terms) if claim_terms else 0.0
        ),
        "shared_content_terms": shared_terms,
        "shared_content_term_count": len(shared_terms),
        "claim_content_term_count": len(claim_terms),
        "evidence_content_term_count": len(evidence_terms),
        "conflict_cue_required": require_conflict_cue,
        "conflict_cues": [],
    }

    if raw_label != "contradiction":
        diagnostics["reason"] = "No guard needed for this raw NLI label."
        return raw_label, diagnostics

    claim_term_coverage = diagnostics["claim_term_coverage"]
    if (
        len(shared_terms) < minimum_shared_terms
        or claim_term_coverage < minimum_claim_term_coverage
    ):
        diagnostics["applied"] = True
        diagnostics["reason"] = (
            "Downgraded NLI contradiction to neutral because the pair has "
            "insufficient normalized content overlap: "
            f"{len(shared_terms)} shared terms and "
            f"{claim_term_coverage:.3f} claim-term coverage; required at least "
            f"{minimum_shared_terms} shared terms and "
            f"{minimum_claim_term_coverage:.3f} coverage. Low topical overlap "
            "is not evidence of contradiction."
        )
        return "neutral", diagnostics

    cues = conflict_cues(claim, evidence)
    diagnostics["conflict_cues"] = cues
    if require_conflict_cue and not cues:
        diagnostics["applied"] = True
        diagnostics["reason"] = (
            "Downgraded NLI contradiction to neutral because the pair has no "
            "detectable conflict cue (negation, modality, number, quantifier "
            "or antonym difference). Topical overlap alone does not show that "
            "the statements disagree."
        )
        return "neutral", diagnostics

    diagnostics["reason"] = (
        "Retained NLI contradiction because the pair meets the minimum "
        "content-overlap check and shows conflict cues "
        f"{cues or '[not required]'}; verify against evidence and held-out tests."
    )
    return raw_label, diagnostics
