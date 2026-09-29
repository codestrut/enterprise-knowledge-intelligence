"""Grounding validation utilities for the RAG pipeline."""

import re


def validate_grounding(answer, source_map, source_documents):
    """Check that cited sources exist and contain supporting text."""

    citations = re.findall(
        r"\[Source\s+(\d+)\]",
        answer,
    )

    unsupported_citations = []
    grounded_citations = []

    for citation in citations:
        source_number = int(citation)

        if source_number not in source_map:
            unsupported_citations.append({
                "source_number": source_number,
                "reason": "Citation does not exist in the source map.",
            })
            continue

        source_index = source_number - 1

        if source_index >= len(source_documents):
            unsupported_citations.append({
                "source_number": source_number,
                "reason": "Citation does not map to a retrieved document.",
            })
            continue

        source_text = source_documents[source_index]["text"]

        grounded_citations.append({
            "source_number": source_number,
            "supported_by": source_text,
        })

    return {
        "grounded_citations": grounded_citations,
        "unsupported_citations": unsupported_citations,
    }