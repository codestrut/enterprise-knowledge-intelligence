"""Thread-safe lazy sharing for expensive inference components across tenants."""

from __future__ import annotations

from threading import Lock
from typing import Any, Callable


class SharedReranker:
    """Share one cross-encoder reranker while tenant indexes remain separate."""

    def __init__(self, factory: Callable[[], Any] | None = None) -> None:
        self._factory = factory
        self._instance: Any | None = None
        self._lock = Lock()

    def rerank(self, query, documents, top_k=5):
        with self._lock:
            if self._instance is None:
                if self._factory is None:
                    from src.retrieval.reranker import Reranker

                    self._factory = Reranker
                self._instance = self._factory()
            return self._instance.rerank(query, documents, top_k=top_k)


class SharedGroundingEvaluator:
    """Share the NLI/grounding evaluator and its model between tenant pipelines."""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._instance: Any | None = None
        self._lock = Lock()

    def evaluate(self, *args, **kwargs):
        with self._lock:
            if self._instance is None:
                self._instance = self._factory()
            return self._instance.evaluate(*args, **kwargs)

    def evaluate_predecomposed(self, *args, **kwargs):
        """Evaluate already-decomposed claims without decomposing them again."""
        with self._lock:
            if self._instance is None:
                self._instance = self._factory()

            evaluator = self._instance
            method = getattr(evaluator, "evaluate_predecomposed", None)

            if callable(method):
                return method(*args, **kwargs)

            # Preserve compatibility with older injected evaluators.
            return evaluator.evaluate(*args, **kwargs)
