"""End-to-end RAG pipeline."""

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.generation.citation_validator import validate_citations
from src.generation.context_builder import build_context
from src.generation.evidence_gate import check_evidence
from src.generation.grounding_evaluator import GroundingEvaluator
from src.generation.llm_client import LLMClient
from src.generation.prompt_builder import build_prompt
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.reranked_retriever import RerankedRetriever


class RAGPipeline:
    """End-to-end retrieval-augmented generation pipeline."""

    def __init__(self, document_path):
        self.document_path = document_path

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

        self.retriever = RerankedRetriever(
            chunks=self.chunks,
            embeddings=self.embeddings,
            embedder=self.embedder,
        )

        self.llm = LLMClient()

        self.grounding_evaluator = GroundingEvaluator(
            embedder=self.embedder,
        )

    def query(self, question, top_k=5):
        """Run the complete RAG pipeline for a question."""

        retrieved_documents = self.retriever.retrieve(
            question,
            top_k=top_k,
        )

        evidence_result = check_evidence(
            retrieved_documents
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

        context, source_map = build_context(
            retrieved_documents
        )

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

        return {
            "question": question,
            "answer": answer,
            "sources": retrieved_documents,
            "source_map": source_map,
            "citations": citation_result["citations"],
            "invalid_citations": citation_result["invalid_citations"],
            "grounding": grounding_result,
            "evidence": evidence_result,
            "refused": False,
        }