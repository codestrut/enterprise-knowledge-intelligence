"""Evidence sufficiency gate for the RAG pipeline."""

DEFAULT_THRESHOLD = 4.3


def check_evidence(retrieved_documents, threshold=DEFAULT_THRESHOLD):
    """Determine whether retrieved evidence is sufficient for generation."""

    if not retrieved_documents:
        return {
            "sufficient": False,
            "score": None,
            "threshold": threshold,
            "reason": "No evidence was retrieved.",
        }

    top_score = max(
        float(document["score"])
        for document in retrieved_documents
    )

    sufficient = top_score >= threshold

    return {
        "sufficient": sufficient,
        "score": top_score,
        "threshold": threshold,
        "reason": (
            "Sufficient evidence found."
            if sufficient
            else "Retrieved evidence does not meet the minimum relevance threshold."
        ),
    }