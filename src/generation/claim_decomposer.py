"""Semantic claim decomposition utilities."""

import json

from src.generation.llm_client import LLMClient


DECOMPOSITION_PROMPT = """You are a claim decomposition component in an enterprise RAG grounding system.

Decompose the CURRENT CLAIM into atomic factual propositions suitable for evidence checking.

Rules:
1. Preserve the claim's meaning exactly. Do not add new factual content.
2. Each output item must be a grammatical, independently verifiable proposition, not a noun fragment.
3. Preserve the original predicate and its arguments when separating genuinely independent clauses.
3a. Preserve who or what performs each action. Never substitute a related entity as the grammatical subject or agent. For example, do not rewrite "The CSF helps executives translate cybersecurity risk into general risk language" as "ERM translates cybersecurity risk into general risk language." If decomposition would change the actor, keep the original claim intact.
4. Do not split a coordinated list of nouns that shares one predicate into malformed fragments. For example,
   "establishing a program, strategy, objectives, policies, and processes" should remain a grammatical
   proposition with that whole list unless the original explicitly asserts separate independent facts.
5. Do not turn "It establishes a program, strategy, and objectives" into fragments such as
   "It establishes a strategy" or "It establishes a objectives". If uncertain, keep the original claim intact.
6. If the claim begins with a reference such as "It", "This", "These", or "They", use the PRIOR ANSWER CONTEXT
   only to resolve the reference when its antecedent is unambiguous. Follow an already-established referent chain;
   do not replace a document/framework/system as the subject with a noun that merely appears inside a prior clause.
   For example, in "The NIST CSF defines GV.RR. It states that leadership is accountable. It also covers supplier
   roles", the final "It" refers to the NIST CSF, not leadership. Replace the reference only when confident.
   If the antecedent is ambiguous, return the original claim unchanged. Do not treat context as evidence or import facts.
7. If the claim is already atomic, return it unchanged (except for an unambiguous pronoun resolution using context).
8. Return ONLY a valid JSON array of strings. Do not return markdown, explanations, or code fences.

PRIOR ANSWER CONTEXT (for reference resolution only; may be empty):
{context}

CURRENT CLAIM:
{claim}
"""


class ClaimDecomposer:
    """Decompose compound claims into atomic factual propositions."""

    def __init__(self, llm_client=None):
        self.llm = llm_client or LLMClient()

    def decompose(self, claim, context=None):
        """Return atomic claims, optionally resolving a local antecedent."""

        claim = claim.strip()

        if not claim:
            return []

        prompt = DECOMPOSITION_PROMPT.format(
            claim=claim,
            context=(context or "").strip(),
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