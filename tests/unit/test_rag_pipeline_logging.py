"""Default RAG logging must not contain request content (questions, answers, passages)."""

import logging

import src.rag_pipeline as rag_pipeline


class RefusingLLM:
    def generate(self, prompt):
        raise AssertionError("The refusal path must not call the LLM.")


class EmptyKnowledgeBase:
    embedder = object()
    chunks = []
    retriever = None
    tenant_id = None


def _pipeline(monkeypatch):
    monkeypatch.setattr(rag_pipeline, "LLMClient", RefusingLLM)
    return rag_pipeline.RAGPipeline(knowledge_base=EmptyKnowledgeBase(), grounding_evaluator=object())


def test_default_logs_contain_no_question_text_or_debug_output(monkeypatch, caplog):
    monkeypatch.delenv("EKIP_DEBUG_RETRIEVAL_LOGGING", raising=False)
    pipeline = _pipeline(monkeypatch)
    caplog.set_level(logging.DEBUG)
    result = pipeline.query("CANARY-QUESTION-7781 confidential launch plan")
    assert result["refused"] is True
    assert "CANARY-QUESTION-7781" not in caplog.text
    assert "[RAG DEBUG]" not in caplog.text


def test_retrieval_debug_logging_requires_the_explicit_flag(monkeypatch, caplog):
    monkeypatch.setenv("EKIP_DEBUG_RETRIEVAL_LOGGING", "true")
    pipeline = _pipeline(monkeypatch)
    caplog.set_level(logging.DEBUG)
    pipeline.query("diagnostic question")
    assert "[RAG DEBUG]" in caplog.text
