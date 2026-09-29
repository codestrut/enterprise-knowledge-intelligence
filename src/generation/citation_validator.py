"""Citation validation utilities for the RAG generation pipeline."""

import re


def validate_citations(answer, source_map):
    """Validate source citations in an LLM-generated answer."""

    citations = re.findall(
        r"\[Source\s+(\d+)\]",
        answer,
    )

    validated_citations = []
    invalid_citations = []

    for citation in citations:
        source_number = int(citation)

        if source_number in source_map:
            validated_citations.append({
                "source_number": source_number,
                **source_map[source_number],
            })
        else:
            invalid_citations.append(source_number)

    return {
        "answer": answer,
        "citations": validated_citations,
        "invalid_citations": invalid_citations,
    }