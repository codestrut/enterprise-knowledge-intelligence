"""Small Ragas wrapper used by the optional EKIP framework POC.

Ragas is an independent judge, not a replacement for EKIP's deterministic
citation, refusal, and claim-grounding gates. Its faithfulness score is
reported separately so the two evaluation systems can be compared.
"""

from __future__ import annotations

import os
from typing import Any


def build_faithfulness_scorer() -> Any:
    """Build Ragas' collections-based Faithfulness metric using OpenAI.

    Requires ``OPENAI_API_KEY``. The judge model can be overridden with
    ``RAGAS_EVALUATOR_MODEL``; defaults to gpt-4o-mini.
    """
    try:
        from openai import AsyncOpenAI
        from ragas.llms import llm_factory
        from ragas.metrics.collections import Faithfulness
    except ImportError as exc:  # pragma: no cover - optional dependency path
        raise RuntimeError(
            "Ragas is not installed. Run: python -m pip install -r requirements.ragas-poc.txt"
        ) from exc

    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY is required for Ragas LLM-as-a-judge evaluation.")

    client = AsyncOpenAI()
    model_name = os.getenv("RAGAS_EVALUATOR_MODEL", "gpt-4o-mini")
    evaluator_llm = llm_factory(model_name, client=client)
    return Faithfulness(llm=evaluator_llm)


async def score_faithfulness(
    scorer: Any,
    *,
    query: str,
    answer: str,
    contexts: list[str],
) -> dict[str, Any]:
    """Score a single generated answer and retain judge reasoning if present."""
    result = await scorer.ascore(
        user_input=query,
        response=answer,
        retrieved_contexts=contexts,
    )
    value = getattr(result, "value", result)
    reason = getattr(result, "reason", None)
    return {"value": float(value), "reason": reason}
