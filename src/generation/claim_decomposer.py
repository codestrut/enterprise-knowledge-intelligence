"""Semantic claim decomposition utilities."""

import json

from src.generation.llm_client import LLMClient


DECOMPOSITION_PROMPT = """You are a claim decomposition component in an enterprise RAG grounding system.

Your task is to decompose a factual claim into atomic factual propositions.

Rules:
1. Preserve the original meaning exactly.
2. Do not add information that is not present in the input claim.
3. Each output claim must express one independently verifiable factual proposition.
4. Preserve the subject when it is implied by the original sentence.
5. Do not split a simple list of actions that belongs to one proposition.
6. If the claim is already atomic, return it unchanged.
7. Return ONLY a valid JSON array of strings.
8. Do not return markdown, explanations, or code fences.

INPUT CLAIM:
{claim}
"""


class ClaimDecomposer:
    """Decompose compound claims into atomic factual propositions."""

    def __init__(self, llm_client=None):
        self.llm = llm_client or LLMClient()

    def decompose(self, claim):
        """Return atomic claims derived from the input claim."""

        claim = claim.strip()

        if not claim:
            return []

        prompt = DECOMPOSITION_PROMPT.format(
            claim=claim
        )

        response = self.llm.generate(prompt)

        try:
            claims = json.loads(response)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Claim decomposer returned invalid JSON."
            ) from exc

        if not isinstance(claims, list):
            raise ValueError(
                "Claim decomposer must return a JSON array."
            )

        if not all(
            isinstance(item, str)
            for item in claims
        ):
            raise ValueError(
                "Every decomposed claim must be a string."
            )

        return [
            item.strip()
            for item in claims
            if item.strip()
        ]