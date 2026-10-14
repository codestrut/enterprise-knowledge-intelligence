"""Bounded, conservative repair for answers with grounding defects."""

from src.generation.prompt_builder import SYSTEM_PROMPT


ABSTENTION_TEXT = (
    "I don't have sufficient evidence in the available knowledge base "
    "to answer that question."
)


def is_explicit_abstention(answer):
    """Return True only for a standalone, recognizable abstention."""
    normalized = " ".join((answer or "").lower().split())
    normalized = normalized.strip().rstrip(".!? ")
    if not normalized:
        return False

    accepted = {
        ABSTENTION_TEXT.lower().rstrip(".!? "),
        "i do not have sufficient evidence in the available knowledge base to answer that question",
        "i cannot answer from the available context",
        "i can't answer from the available context",
        "i cannot determine from the available context",
        "i can't determine from the available context",
        "the available information is insufficient to answer this question",
    }
    # Do not treat a mixed answer containing an abstention phrase plus factual
    # content as a safe refusal; it must be a standalone abstention.
    return normalized in accepted


def answer_passes_grounding(answer, grounding, invalid_citations):
    """Require valid citations and fully grounded claims, or explicit abstention.

    An empty grounding list is not considered a grounded factual answer. This
    avoids treating parser-invisible/uncited content as automatically safe.
    """
    if invalid_citations:
        return False

    if is_explicit_abstention(answer):
        return True

    if not grounding:
        return False

    return all(item.get("status") == "grounded" for item in grounding)


def summarize_answer_attempt(answer, grounding, invalid_citations):
    """Return non-sensitive diagnostics for one generated answer attempt."""
    import re
    from collections import Counter

    grounding = grounding or []
    invalid_citations = invalid_citations or []
    statuses = [item.get("status", "unknown") for item in grounding]
    status_counts = dict(Counter(statuses))

    return {
        "empty_answer": not bool((answer or "").strip()),
        "explicit_abstention": is_explicit_abstention(answer),
        "citation_marker_count": len(
            re.findall(r"\[Source\s+\d+\]", answer or "")
        ),
        "grounding_claim_count": len(grounding),
        "grounding_status_counts": status_counts,
        "invalid_citation_count": len(invalid_citations),
        "passes_grounding": answer_passes_grounding(
            answer, grounding, invalid_citations
        ),
    }


def summarize_grounding_details(grounding, max_claims=8, max_atomic_claims=12,
                                max_sources=5, max_evidence_per_source=2,
                                max_text_chars=900):
    """Return bounded claim/evidence details for explicit local debugging only.

    Callers must gate this with EKIP_DEBUG_GENERATION_DETAILS because claim and
    source snippets can contain tenant-confidential content.
    """
    def clip(value):
        text = str(value or "")
        return text[:max_text_chars]

    def summarize_evidence(item):
        result = {
            "label": item.get("label"),
            "raw_label": item.get("raw_label"),
            "evidence": clip(item.get("evidence")),
        }
        probabilities = item.get("probabilities")
        if isinstance(probabilities, dict):
            result["probabilities"] = probabilities
        for guard_name in ("relation_guard", "support_guard"):
            guard = item.get(guard_name)
            if isinstance(guard, dict):
                keys = (
                    "applied", "reason", "conflict_cues", "claim_term_coverage",
                    "term_coverage", "ordered_coverage", "protected_markers_match",
                )
                result[guard_name] = {
                    key: guard[key] for key in keys if key in guard
                }
        return result

    def summarize_source(source):
        row = {
            "source_number": source.get("source_number"),
            "label": source.get("label"),
            "conflict_detected": source.get("conflict_detected"),
        }
        evidence = source.get("evidence")
        if isinstance(evidence, list):
            row["evidence"] = [
                summarize_evidence(item) for item in evidence[:max_evidence_per_source]
                if isinstance(item, dict)
            ]
        return row

    output = []
    items = list(grounding or [])
    # Put non-grounded claims first so the bounded preview surfaces the failure.
    items.sort(key=lambda item: 0 if item.get("status") in {"unsupported", "contradicted"} else 1)
    for item in items[:max_claims]:
        claim_row = {
            "claim": clip(item.get("claim")),
            "status": item.get("status", "unknown"),
        }
        atomic_claims = item.get("atomic_claims")
        if isinstance(atomic_claims, list):
            atom_rows = []
            for atom in atomic_claims[:max_atomic_claims]:
                if not isinstance(atom, dict):
                    continue
                atom_row = {
                    "claim": clip(atom.get("claim")),
                    "status": atom.get("status"),
                }
                sources = atom.get("sources")
                if isinstance(sources, list):
                    atom_row["sources"] = [
                        summarize_source(source) for source in sources[:max_sources]
                        if isinstance(source, dict)
                    ]
                atom_rows.append(atom_row)
            claim_row["atomic_claims"] = atom_rows
        sources = item.get("sources")
        if isinstance(sources, list):
            claim_row["sources"] = [
                summarize_source(source) for source in sources[:max_sources]
                if isinstance(source, dict)
            ]
        output.append(claim_row)
    return output


def build_grounded_subset_answer(grounding, max_claims=6):
    """Build a cited candidate from atomic claims already labelled grounded.

    This is a conservative fallback after model-based repair fails. It never
    rewrites a claim: it copies only evaluator-approved claim text and attaches
    a source number already associated with that grounded claim. The caller
    must still revalidate citations and rerun grounding on the assembled answer.
    """
    selected = []
    seen_claims = set()

    for parent in grounding or []:
        atomic_claims = parent.get("atomic_claims")
        if isinstance(atomic_claims, list) and atomic_claims:
            candidates = atomic_claims
        else:
            candidates = [parent] if parent.get("status") == "grounded" else []

        for item in candidates:
            if not isinstance(item, dict) or item.get("status") != "grounded":
                continue

            claim = " ".join(str(item.get("claim") or "").split()).strip(" -*\t\n")
            if not claim:
                continue

            normalized_claim = claim.casefold()
            if normalized_claim in seen_claims:
                continue

            sources = item.get("sources")
            if not isinstance(sources, list):
                continue

            safe_sources = [
                source for source in sources
                if isinstance(source, dict)
                and source.get("source_number") is not None
                and source.get("conflict_detected") is not True
                and str(source.get("label", "")).lower()
                    not in {"contradiction", "contradicted"}
            ]
            if not safe_sources:
                continue

            # Prefer an explicitly entailing source if one is available.
            safe_sources.sort(
                key=lambda source: str(source.get("label", "")).lower()
                not in {"entailment", "entailed"}
            )
            source_number = safe_sources[0]["source_number"]
            selected.append(f"- {claim} [Source {source_number}]")
            seen_claims.add(normalized_claim)

            if len(selected) >= max_claims:
                return "\n".join(selected)

    return "\n".join(selected)


def summarize_grounding_issues(grounding, invalid_citations):
    """Return a concise, non-sensitive summary suitable for a repair prompt."""
    issues = []
    for item in grounding:
        status = item.get("status")
        if status in {"unsupported", "contradicted"}:
            issues.append({
                "claim": item.get("claim", ""),
                "status": status,
            })
    if invalid_citations:
        issues.append({
            "claim": "One or more citations refer to nonexistent sources.",
            "status": "invalid_citation",
        })
    if not grounding and not invalid_citations:
        issues.append({
            "claim": "The draft contains no verifiable cited claims.",
            "status": "unverified_answer",
        })
    return issues



def build_answerability_recovery_prompt(query, context, draft_answer):
    """Recover from a model abstention when the evidence gate passed.

    A relevance score is not proof of answerability, so the model must inspect
    the actual passages and answer only when they directly support a response.
    """
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "ANSWERABILITY RECOVERY MODE\n"
        "The retrieved passages passed EKIP's evidence-relevance gate, but the "
        "previous draft abstained. That draft is not evidence that the question "
        "is unanswerable. Re-read the supplied context and determine whether it "
        "directly answers the user's question. If it does, provide the narrowest "
        "complete answer supported by the passages, with an exact [Source N] "
        "citation immediately after every factual sentence or bullet. Do not "
        "add background knowledge, assumptions, or unsupported details. If the "
        "passages are relevant but do not actually answer the question, retain "
        f"this exact abstention: {ABSTENTION_TEXT}\n\n"
        f"USER QUESTION:\n{query}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"PREVIOUS DRAFT (not evidence):\n{draft_answer}\n\n"
        "Return only the answer or the exact abstention text."
    )

def build_repair_prompt(query, context, draft_answer, issues):
    """Ask for one evidence-constrained correction without expanding claims."""
    return (
        f"{SYSTEM_PROMPT}\n\n"
        "GROUNDING REPAIR MODE\n"
        "The draft answer below failed the grounding checks. Rewrite it using "
        "only claims directly supported by the supplied context. Do not add "
        "new facts, background knowledge, assumptions, or plausible details. "
        "Remove any claim that cannot be directly supported. Preserve source "
        "scope, modality, actor, and conditions. Preserve semantic roles exactly: "
        "keep the same subject/agent, action, recipient/object, and direction. "
        "Never reverse active/passive roles; for example, if the source says "
        "'executives receive significant input', do not write 'executives provide "
        "input'. Do not add interpretive bridge claims such as 'this supports' "
        "unless the source explicitly states that relationship. If one clause in "
        "a compound sentence is unsupported, delete that clause and retain only "
        "the shortest directly supported answer. If sources disagree about the "
        "same fact and no authoritative source or effective-date precedence is "
        "shown, do not select a value arbitrarily: report each source's claim "
        "separately with its own citation, or abstain if the disagreement cannot "
        "be stated safely. Put an exact [Source N] "
        "citation immediately after every factual sentence or bullet, and use "
        "only source numbers present in the context. Do not cite a source merely "
        "because it discusses a related topic. If no answer can be supported, "
        f"output exactly: {ABSTENTION_TEXT}\n\n"
        f"USER QUESTION:\n{query}\n\n"
        f"CONTEXT:\n{context}\n\n"
        f"DRAFT ANSWER TO CORRECT (not evidence):\n{draft_answer}\n\n"
        f"GROUNDING FLAGS (review signals; verify against context):\n{issues}\n\n"
        "Return only the corrected answer, without explaining the repair."
    )
