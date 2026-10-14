"""Optional LlamaIndex adapter for EKIP's existing hybrid retriever.

This module deliberately does not replace EKIP's chunking, embeddings, FAISS,
BM25, reciprocal-rank fusion, citation validator, or grounding gates. It adapts
the existing hybrid retriever to LlamaIndex nodes and uses LlamaIndex's local
SentenceTransformerRerank postprocessor as an experimental alternative to
EKIP's custom cross-encoder wrapper.

The package is optional: importing this module does not require LlamaIndex.
Creating the framework retriever does require ``llama-index-core`` to be
installed via requirements.framework-poc.txt.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from typing import Any, Mapping


DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _require_llamaindex() -> tuple[Any, Any, Any, Any, Any]:
    """Load optional LlamaIndex classes with an actionable error."""
    try:
        from llama_index.core import QueryBundle
        # Core ships this postprocessor; use the documented core import.
        from llama_index.core.postprocessor import SentenceTransformerRerank
        from llama_index.core.retrievers import BaseRetriever
        from llama_index.core.schema import NodeWithScore, TextNode
    except ImportError as exc:  # pragma: no cover - exercised on optional setup
        raise RuntimeError(
            "LlamaIndex is not installed. Activate the project's virtualenv and "
            "run: python -m pip install -r requirements.framework-poc.txt"
        ) from exc
    return QueryBundle, SentenceTransformerRerank, BaseRetriever, NodeWithScore, TextNode


def _metadata_value(value: Any) -> Any:
    """Convert metadata to values safe for LlamaIndex/Pydantic serialization."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "item"):
        try:
            scalar = value.item()
            if scalar is None or isinstance(scalar, (str, int, float, bool)):
                return scalar
        except (ValueError, TypeError):
            pass
    if isinstance(value, (list, tuple, set)):
        return json.dumps(list(value), ensure_ascii=False, default=str)
    if isinstance(value, Mapping):
        return json.dumps(dict(value), ensure_ascii=False, default=str, sort_keys=True)
    return str(value)


def normalize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return clean metadata while retaining EKIP's source/provenance fields."""
    if not metadata:
        return {}
    return {
        str(key): _metadata_value(value)
        for key, value in metadata.items()
        if value is not None
    }


def stable_node_id(record: Mapping[str, Any], ordinal: int = 0) -> str:
    """Resolve the document-scoped chunk identity, with a stable fallback."""
    metadata = record.get("metadata") or {}
    for key in ("chunk_key", "node_id", "chunk_id"):
        value = metadata.get(key)
        if value is not None:
            if key == "chunk_id" and metadata.get("document_id") is not None:
                return f"{metadata['document_id']}:{value}"
            return str(value)
    fingerprint = hashlib.sha256(
        str(record.get("text", "")).encode("utf-8")
    ).hexdigest()[:20]
    return f"ekip-chunk-{ordinal}-{fingerprint}"


class LlamaIndexRerankedRetriever:
    """Drop-in retriever adapter returning EKIP's existing dictionary schema.

    Args:
        hybrid_retriever: EKIP HybridRetriever instance (dense + BM25 + RRF).
        candidate_k: Number of candidates to retrieve before reranking.
        reranker_model: SentenceTransformers cross-encoder model used by
            LlamaIndex's ``SentenceTransformerRerank``.
        postprocessor: Optional injected postprocessor for unit tests. Normal
            application use should omit this argument.

    The output records have the same shape as EKIP's existing retrievers:
    ``{"text": str, "metadata": dict, "score": float}``.
    """

    def __init__(
        self,
        hybrid_retriever: Any,
        candidate_k: int = 20,
        reranker_model: str = DEFAULT_RERANKER_MODEL,
        postprocessor: Any | None = None,
    ) -> None:
        if candidate_k <= 0:
            raise ValueError("candidate_k must be greater than zero.")
        (
            self._QueryBundle,
            SentenceTransformerRerank,
            BaseRetriever,
            NodeWithScore,
            TextNode,
        ) = _require_llamaindex()

        if not callable(getattr(hybrid_retriever, "retrieve", None)):
            raise TypeError("hybrid_retriever must expose retrieve(query, top_k, candidate_k).")

        self.hybrid_retriever = hybrid_retriever
        self.candidate_k = int(candidate_k)
        self.reranker_model = reranker_model
        self._NodeWithScore = NodeWithScore
        self._TextNode = TextNode

        class _EKIPBaseRetriever(BaseRetriever):
            """Translate EKIP records to LlamaIndex nodes."""

            def __init__(inner_self) -> None:
                super().__init__()

            def _retrieve(inner_self, query_bundle: Any) -> list[Any]:
                query = query_bundle.query_str
                signature = inspect.signature(hybrid_retriever.retrieve)
                kwargs: dict[str, Any] = {"top_k": self.candidate_k}
                if "candidate_k" in signature.parameters:
                    kwargs["candidate_k"] = self.candidate_k
                records = hybrid_retriever.retrieve(query, **kwargs)

                nodes = []
                for ordinal, record in enumerate(records):
                    text = str(record.get("text", ""))
                    if not text.strip():
                        continue
                    metadata = normalize_metadata(record.get("metadata"))
                    node = TextNode(
                        id_=stable_node_id(record, ordinal),
                        text=text,
                        metadata=metadata,
                    )
                    raw_score = record.get("score", 0.0)
                    try:
                        score = float(raw_score) if raw_score is not None else 0.0
                    except (TypeError, ValueError):
                        score = 0.0
                    nodes.append(NodeWithScore(node=node, score=score))
                return nodes

        self._base_retriever = _EKIPBaseRetriever()
        self._postprocessor = postprocessor or SentenceTransformerRerank(
            model=reranker_model,
            top_n=candidate_k,
            # Do not permit custom remote model code to execute for this POC.
            trust_remote_code=False,
        )

    def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve candidates, rerank using LlamaIndex, return EKIP records."""
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string.")
        if top_k <= 0:
            raise ValueError("top_k must be greater than zero.")

        candidates = self._base_retriever.retrieve(query)
        reranked = self._postprocessor.postprocess_nodes(
            candidates,
            query_str=query,
        )

        results: list[dict[str, Any]] = []
        for item in reranked[:top_k]:
            node = item.node
            score = getattr(item, "score", None)
            results.append(
                {
                    "text": node.text,
                    "metadata": normalize_metadata(getattr(node, "metadata", {})),
                    "score": float(score) if score is not None else 0.0,
                }
            )
        return results
