
"""End-to-end RAG pipeline with retrieval diagnostics."""

import logging
import os

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.generation.citation_validator import validate_citations
from src.generation.answer_repair import (
    ABSTENTION_TEXT,
    answer_passes_grounding,
    build_answerability_recovery_prompt,
    build_grounded_subset_answer,
    build_repair_prompt,
    is_explicit_abstention,
    summarize_grounding_issues,
    summarize_answer_attempt,
    summarize_grounding_details,
)
from src.generation.context_builder import build_context
from src.generation.evidence_gate import check_evidence
from src.generation.grounding_evaluator import GroundingEvaluator
from src.generation.llm_client import LLMClient
from src.generation.prompt_builder import build_prompt
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.reranked_retriever import RerankedRetriever

logger = logging.getLogger(__name__)


class RAGPipeline:
    """End-to-end retrieval-augmented generation pipeline."""

    def __init__(self, document_path=None, knowledge_base=None, retrieval_backend=None):
        if document_path is None and knowledge_base is None:
            raise ValueError(
                "Provide either document_path or knowledge_base."
            )

        self.document_path = document_path
        self.knowledge_base = knowledge_base
        self.retrieval_backend = (
            retrieval_backend or os.getenv("EKIP_RETRIEVAL_BACKEND", "custom")
        ).strip().lower()
        if self.retrieval_backend not in {"custom", "llamaindex"}:
            raise ValueError(
                "retrieval_backend must be 'custom' or 'llamaindex'."
            )
        self._framework_retriever = None
        self._framework_hybrid_source = None

        if knowledge_base is not None:
            # Reuse the knowledge base's embedder and live retriever.
            self.embedder = knowledge_base.embedder
            self.chunks = knowledge_base.chunks
            self.embeddings = None
            self.retriever = None
        else:
            documents = load_pdf(document_path)
            self.embedder = Embedder()

            self.chunks = chunk_documents(
                documents,
                tokenizer=self.embedder.model.tokenizer,
                chunk_size=200,
                overlap=30,
            )

            self.embeddings = self.embedder.embed_documents(
                self.chunks
            )

            if self.retrieval_backend == "custom":
                self.retriever = RerankedRetriever(
                    chunks=self.chunks,
                    embeddings=self.embeddings,
                    embedder=self.embedder,
                )
            else:
                # Optional path: preserve EKIP's chunking, embeddings and hybrid
                # retrieval, but replace only the reranker with LlamaIndex's
                # SentenceTransformerRerank postprocessor.
                from src.frameworks.llamaindex_retriever import (
                    LlamaIndexRerankedRetriever,
                )
                from src.retrieval.hybrid_retriever import HybridRetriever

                hybrid_retriever = HybridRetriever(
                    chunks=self.chunks,
                    embeddings=self.embeddings,
                    embedder=self.embedder,
                )
                self.retriever = LlamaIndexRerankedRetriever(
                    hybrid_retriever=hybrid_retriever,
                    candidate_k=20,
                )

        self.llm = LLMClient()

        self.grounding_evaluator = GroundingEvaluator(
            embedder=self.embedder,
        )

    def query(self, question, top_k=5):
        """Run retrieval, generation, citation validation and grounding."""

        if self.knowledge_base is not None:
            # Resolve the current retriever so document changes are visible.
            active_retriever = self.knowledge_base.retriever
            if self.retrieval_backend == "llamaindex":
                # Recreate only when the knowledge-base backend swaps its native
                # hybrid retriever (for example after an index replacement).
                hybrid_source = active_retriever.hybrid_retriever
                if (
                    self._framework_retriever is None
                    or self._framework_hybrid_source is not hybrid_source
                ):
                    from src.frameworks.llamaindex_retriever import (
                        LlamaIndexRerankedRetriever,
                    )
                    self._framework_retriever = LlamaIndexRerankedRetriever(
                        hybrid_retriever=hybrid_source,
                        candidate_k=20,
                    )
                    self._framework_hybrid_source = hybrid_source
                active_retriever = self._framework_retriever
            chunk_count = len(self.knowledge_base.chunks)
        else:
            active_retriever = self.retriever
            chunk_count = len(self.chunks)

        logger.info("[RAG DEBUG] Question: %s", question)
        logger.info(
            "[RAG DEBUG] Active retriever exists: %s",
            active_retriever is not None,
        )
        logger.info("[RAG DEBUG] Knowledge-base chunks: %d", chunk_count)

        if active_retriever is None:
            retrieved_documents = []
            logger.warning(
                "[RAG DEBUG] No active retriever; retrieval skipped."
            )
        else:
            hybrid = active_retriever.hybrid_retriever

            logger.info(
                "[RAG DEBUG] Hybrid chunks: %d",
                len(hybrid.chunks),
            )
            logger.info(
                "[RAG DEBUG] FAISS vectors: %d",
                hybrid.vector_retriever.vector_store.index.ntotal,
            )
            logger.info(
                "[RAG DEBUG] Vector chunks: %d",
                len(hybrid.vector_retriever.chunks),
            )
            logger.info(
                "[RAG DEBUG] BM25 chunks: %d",
                len(hybrid.bm25_retriever.chunks),
            )

            # Probe the hybrid stage independently to determine whether
            # candidates exist before cross-encoder reranking.
            try:
                hybrid_results = hybrid.retrieve(
                    question,
                    top_k=max(top_k, 5),
                    candidate_k=10,
                )

                logger.info(
                    "[RAG DEBUG] Hybrid candidates: %d",
                    len(hybrid_results),
                )

                for index, document in enumerate(
                    hybrid_results[:3], start=1
                ):
                    metadata = document.get("metadata", {})
                    logger.info(
                        "[RAG DEBUG] Hybrid result %d: score=%s, "
                        "document_id=%s, page=%s",
                        index,
                        document.get("score"),
                        metadata.get("document_id"),
                        metadata.get("page"),
                    )

            except Exception:
                logger.exception(
                    "[RAG DEBUG] Hybrid retrieval probe failed."
                )

            # Run the original production retrieval path.
            try:
                retrieved_documents = active_retriever.retrieve(
                    question,
                    top_k=top_k,
                )
            except Exception:
                logger.exception(
                    "[RAG DEBUG] Full retrieval/reranking failed."
                )
                raise

            logger.info(
                "[RAG DEBUG] Final retrieved documents: %d",
                len(retrieved_documents),
            )

            for index, document in enumerate(
                retrieved_documents[:3], start=1
            ):
                metadata = document.get("metadata", {})
                logger.info(
                    "[RAG DEBUG] Final result %d: score=%s, "
                    "document_id=%s, page=%s",
                    index,
                    document.get("score"),
                    metadata.get("document_id"),
                    metadata.get("page"),
                )

        evidence_result = check_evidence(retrieved_documents)

        logger.info(
            "[RAG DEBUG] Evidence sufficient: %s; reason: %s",
            evidence_result["sufficient"],
            evidence_result["reason"],
        )

        if not evidence_result["sufficient"]:
            return {
                "question": question,
                "answer": (
                    "I don't have sufficient evidence in the "
                    "available knowledge base to answer that question."
                ),
                "sources": retrieved_documents,
                "source_map": {},
                "citations": [],
                "invalid_citations": [],
                "grounding": [],
                "evidence": evidence_result,
                "refused": True,
            }

        context, source_map = build_context(retrieved_documents)

        prompt = build_prompt(
            query=question,
            context=context,
        )

        answer = self.llm.generate(prompt)

        citation_result = validate_citations(
            answer=answer,
            source_map=source_map,
        )

        grounding_result = self.grounding_evaluator.evaluate(
            answer=answer,
            source_map=source_map,
            source_documents=retrieved_documents,
        )

        repair_result = {
            "attempted": False,
            "accepted": False,
            "reason": "initial_answer_passed_grounding",
            "initial_issue_count": 0,
        }

        initial_abstention = is_explicit_abstention(answer)
        initial_answer_passes = answer_passes_grounding(
            answer,
            grounding_result,
            citation_result["invalid_citations"],
        )
        # Record why this attempt passed or failed without exposing generated
        # text by default. Detailed draft text is available only by explicit
        # local opt-in for debugging.
        repair_result["initial_diagnostics"] = summarize_answer_attempt(
            answer,
            grounding_result,
            citation_result["invalid_citations"],
        )
        include_generation_text = os.getenv(
            "EKIP_DEBUG_GENERATION_DETAILS", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        if include_generation_text:
            repair_result["debug_initial_answer"] = (answer or "")[:3000]
            repair_result["debug_initial_grounding"] = summarize_grounding_details(
                grounding_result
            )
            repair_result["debug_initial_invalid_citations"] = (
                citation_result["invalid_citations"][:20]
            )
        # Explicit model abstentions normally pass the grounding gate. When
        # retrieval has already passed the evidence-relevance gate, however,
        # try one bounded recovery against the actual passages before accepting
        # that abstention. The relevance gate alone does not establish that the
        # question is answerable; the recovered answer must still ground.
        if initial_abstention or not initial_answer_passes:
            if initial_abstention:
                issues = [{
                    "claim": (
                        "The draft abstained despite passing the evidence-"
                        "relevance gate; verify whether the supplied passages "
                        "directly answer the question."
                    ),
                    "status": "premature_abstention",
                }]
                repair_reason = "initial_abstention_with_sufficient_relevance"
            else:
                issues = summarize_grounding_issues(
                    grounding_result,
                    citation_result["invalid_citations"],
                )
                repair_reason = "grounding_or_citation_check_failed"

            repair_result.update({
                "attempted": True,
                "reason": repair_reason,
                "mode": "answerability_recovery" if initial_abstention else "grounding_repair",
                "initial_issue_count": len(issues),
            })

            try:
                if initial_abstention:
                    repair_prompt = build_answerability_recovery_prompt(
                        query=question,
                        context=context,
                        draft_answer=answer,
                    )
                else:
                    repair_prompt = build_repair_prompt(
                        query=question,
                        context=context,
                        draft_answer=answer,
                        issues=issues,
                    )
                repaired_answer = self.llm.generate(repair_prompt)
                repaired_citations = validate_citations(
                    answer=repaired_answer,
                    source_map=source_map,
                )
                repaired_grounding = self.grounding_evaluator.evaluate(
                    answer=repaired_answer,
                    source_map=source_map,
                    source_documents=retrieved_documents,
                )
                repair_result["repair_diagnostics"] = summarize_answer_attempt(
                    repaired_answer,
                    repaired_grounding,
                    repaired_citations["invalid_citations"],
                )
                if include_generation_text:
                    repair_result["debug_repair_answer"] = (
                        repaired_answer or ""
                    )[:3000]
                    repair_result["debug_repair_grounding"] = (
                        summarize_grounding_details(repaired_grounding)
                    )
                    repair_result["debug_repair_invalid_citations"] = (
                        repaired_citations["invalid_citations"][:20]
                    )

                # A repeat abstention is not a successful recovery. Keep the
                # safe refusal, but make the failed recovery visible.
                recovered_answer_is_grounded = (
                    not is_explicit_abstention(repaired_answer)
                    and answer_passes_grounding(
                        repaired_answer,
                        repaired_grounding,
                        repaired_citations["invalid_citations"],
                    )
                )
                if recovered_answer_is_grounded:
                    answer = repaired_answer
                    citation_result = repaired_citations
                    grounding_result = repaired_grounding
                    repair_result.update({
                        "accepted": True,
                        "reason": (
                            "answerability_recovery_passed_grounding"
                            if initial_abstention
                            else "repair_passed_grounding"
                        ),
                    })
                else:
                    # The model can leave some directly supported atomic claims
                    # inside a draft that fails as a whole. Salvage only those
                    # already-grounded atoms, cite their recorded source, then
                    # run the exact same citation and grounding checks again.
                    # This is not an exemption from grounding: the subset must
                    # independently pass before it can be returned.
                    subset_answer = build_grounded_subset_answer(
                        repaired_grounding
                    )
                    subset_accepted = False
                    if subset_answer:
                        subset_citations = validate_citations(
                            answer=subset_answer,
                            source_map=source_map,
                        )
                        subset_grounding = self.grounding_evaluator.evaluate(
                            answer=subset_answer,
                            source_map=source_map,
                            source_documents=retrieved_documents,
                        )
                        subset_accepted = answer_passes_grounding(
                            subset_answer,
                            subset_grounding,
                            subset_citations["invalid_citations"],
                        )
                        if subset_accepted:
                            answer = subset_answer
                            citation_result = subset_citations
                            grounding_result = subset_grounding
                            repair_result.update({
                                "accepted": True,
                                "reason": "repair_grounded_subset_passed_grounding",
                                "grounded_subset_used": True,
                                "grounded_subset_claim_count": len(subset_grounding),
                            })

                    if not subset_accepted:
                        # Keep the fail-closed behavior if no safe subset exists
                        # or its independent validation fails.
                        answer = ABSTENTION_TEXT
                        citation_result = validate_citations(
                            answer=answer,
                            source_map=source_map,
                        )
                        grounding_result = []
                        repair_result.update({
                            "accepted": False,
                            "reason": (
                                "answerability_recovery_still_abstained"
                                if is_explicit_abstention(repaired_answer)
                                else "repair_failed_grounding_abstained"
                            ),
                            "grounded_subset_used": False,
                        })

            except Exception:
                logger.exception("Grounding/recovery attempt failed; abstaining.")
                answer = ABSTENTION_TEXT
                citation_result = validate_citations(
                    answer=answer,
                    source_map=source_map,
                )
                grounding_result = []
                repair_result.update({
                    "accepted": False,
                    "reason": "repair_error_abstained",
                })

        refused = is_explicit_abstention(answer)

        return {
            "question": question,
            "answer": answer,
            "sources": retrieved_documents,
            "source_map": source_map,
            "citations": citation_result["citations"],
            "invalid_citations": citation_result["invalid_citations"],
            "grounding": grounding_result,
            "evidence": evidence_result,
            "refused": refused,
            "generation_repair": repair_result,
        }
