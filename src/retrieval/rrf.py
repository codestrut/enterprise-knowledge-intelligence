"""Reciprocal Rank Fusion utilities."""


def reciprocal_rank_fusion(rankings, k=60):
    """Combine multiple ranked lists using Reciprocal Rank Fusion."""

    scores = {}

    for ranking in rankings:

        for rank, document_id in enumerate(ranking, start=1):

            if document_id not in scores:
                scores[document_id] = 0.0

            scores[document_id] += 1 / (k + rank)

    ranked_documents = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    return ranked_documents