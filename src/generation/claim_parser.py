"""Claim and citation parsing utilities."""

import re


def parse_claims(answer):
    """Extract claims and their associated source citations."""

    claims = []

    citation_pattern = re.compile(
        r"(?P<citations>(?:\[Source\s+\d+\]\s*)+)"
    )

    citation_match = citation_pattern.search(answer)

    if not citation_match:
        return claims

    text = answer[:citation_match.start()].strip()
    citation_text = citation_match.group("citations")

    source_numbers = [
        int(citation)
        for citation in re.findall(
            r"\[Source\s+(\d+)\]",
            citation_text,
        )
    ]

    sentences = re.split(
        r"(?<=[.!?])\s+",
        text,
    )

    for sentence in sentences:

        sentence = sentence.strip()

        if not sentence:
            continue

        claims.append({
            "claim": sentence,
            "source_numbers": source_numbers,
        })

    return claims