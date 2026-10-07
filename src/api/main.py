"""FastAPI application for the Enterprise Knowledge Intelligence Platform."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.rag_pipeline import RAGPipeline


DOCUMENT_PATH = "data/raw/nist_csf_2.0.pdf"


app = FastAPI(
    title="Enterprise Knowledge Intelligence Platform",
    version="1.0.0",
)


class QueryRequest(BaseModel):
    """Request model for RAG queries."""

    question: str = Field(
        min_length=1,
        description="Question to ask the knowledge base.",
    )

    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of documents to retrieve.",
    )


pipeline = RAGPipeline(
    document_path=DOCUMENT_PATH,
)


@app.get("/health")
def health_check():
    """Return the API health status."""

    return {
        "status": "ok",
    }


@app.post("/query")
def query(request: QueryRequest):
    """Answer a question using the enterprise knowledge base."""

    result = pipeline.query(
        question=request.question,
        top_k=request.top_k,
    )

    return result