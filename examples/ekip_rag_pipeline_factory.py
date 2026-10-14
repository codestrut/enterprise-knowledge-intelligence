"""Example adapter for EKIP's current single-document RAGPipeline.

This adapter supports one document_path per corpus configuration, matching
EKIP's present single-PDF RAGPipeline constructor. For a live multi-document
KnowledgeBase, replace this factory with one that builds/loads the intended
corpus once and returns RAGPipeline(knowledge_base=...).
"""

from collections.abc import Mapping
from typing import Any


def build_pipeline(corpus_config: Mapping[str, Any]):
    """Build the current pipeline for a corpus configured by document_path."""
    document_path = corpus_config.get("document_path")
    if not isinstance(document_path, str) or not document_path.strip():
        raise ValueError(
            f"Corpus {corpus_config.get('id')!r} needs a non-empty document_path "
            "for this single-document adapter."
        )

    # Import lazily so deterministic benchmark harness tests do not load models.
    from src.rag_pipeline import RAGPipeline

    return RAGPipeline(document_path=document_path)
