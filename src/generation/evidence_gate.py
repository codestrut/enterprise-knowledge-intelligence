
"""Evidence sufficiency gate for the RAG pipeline."""

import math


# Calibrated against the current NIST CSF 2.0 benchmark.
# This is a starting threshold, not a universal relevance score.
DEFAULT_THRESHOLD = 4.3


def check_evidence(retrieved_documents, threshold=DEFAULT_THRESHOLD):
    """
    Determine whether retrieved evidence passes the relevance threshold.

    The gate decides whether to proceed with generation. Passing the gate
    does not prove that the question is answerable or that every claim is
    supported; citation validation and claim-level grounding remain required.
    """

    if threshold is None:
        raise ValueError(
            "An evidence threshold must be configured."
        )

    threshold = float(threshold)

    if not retrieved_documents:
        return {
            "sufficient": False,
            "score": None,
            "threshold": threshold,
            "reason": "No evidence was retrieved.",
        }

    valid_documents = [
        document
        for document in retrieved_documents
        if isinstance(document.get("text"), str)
        and document["text"].strip()
    ]

    if not valid_documents:
        return {
            "sufficient": False,
            "score": None,
            "threshold": threshold,
            "reason": "No usable evidence was retrieved.",
        }

    scores = []

    for document in valid_documents:
        raw_score = document.get("score")

        if raw_score is None:
            continue

        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue

        if math.isfinite(score):
            scores.append(score)

    if not scores:
        return {
            "sufficient": False,
            "score": None,
            "threshold": threshold,
            "reason": "No valid evidence relevance scores were available.",
        }

    best_score = max(scores)
    sufficient = best_score >= threshold

    return {
        "sufficient": sufficient,
        "score": best_score,
        "threshold": threshold,
        "reason": (
            "Evidence passed the relevance threshold."
            if sufficient
            else (
                "Retrieved evidence did not meet the relevance "
                "threshold; generation should be refused."
            )
        ),
    }
