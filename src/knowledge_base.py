"""Knowledge base management for dynamic document ingestion."""

from pathlib import Path
from uuid import uuid4

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf
from src.retrieval.reranked_retriever import RerankedRetriever


class KnowledgeBase:
    """Manage document ingestion and retrieval indexes."""

    def __init__(
        self,
        embedder=None,
        chunk_size=200,
        overlap=30,
    ):
        self.embedder = embedder or Embedder()
        self.chunk_size = chunk_size
        self.overlap = overlap

        self.documents = {}
        self.chunks = []
        self.retriever = None

    def add_pdf(self, file_path, document_id=None):
        """Ingest a PDF and add its chunks to the retrieval indexes."""

        path = Path(file_path).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(f"PDF file not found: {path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError("Only PDF documents are supported currently.")

        document_id = document_id or str(uuid4())

        if document_id in self.documents:
            raise ValueError(f"Document ID already exists: {document_id}")

        pages = load_pdf(str(path))

        if not pages:
            raise ValueError(f"No pages could be extracted from: {path.name}")

        for page in pages:
            page["metadata"]["document_id"] = document_id
            page["metadata"]["filename"] = path.name

        new_chunks = chunk_documents(
            pages,
            tokenizer=self.embedder.model.tokenizer,
            chunk_size=self.chunk_size,
            overlap=self.overlap,
            document_id=document_id,
        )

        if not new_chunks:
            raise ValueError(
                f"No text chunks could be extracted from: {path.name}"
            )

        embeddings = self.embedder.embed_documents(new_chunks)

        if self.retriever is None:
            self.retriever = RerankedRetriever(
                chunks=new_chunks,
                embeddings=embeddings,
                embedder=self.embedder,
            )
        else:
            self.retriever.add_documents(new_chunks)

        self.chunks.extend(new_chunks)

        record = {
            "document_id": document_id,
            "filename": path.name,
            "source": str(path),
            "page_count": len(pages),
            "chunk_count": len(new_chunks),
            "status": "indexed",
        }

        self.documents[document_id] = record

        return record.copy()

    def list_documents(self):
        """Return registered documents."""

        return [
            record.copy()
            for record in self.documents.values()
        ]

    def query(self, question, top_k=5):
        """Retrieve relevant chunks from the knowledge base."""

        if self.retriever is None:
            return []

        return self.retriever.retrieve(question, top_k=top_k)


    def delete_document(self, document_id):
        """Remove a document and rebuild its retrieval indexes safely."""
        if document_id not in self.documents:
            raise KeyError(f"Document not found: {document_id}")

        remaining_chunks = [
            chunk
            for chunk in self.chunks
            if chunk["metadata"].get("document_id") != document_id
        ]

        replacement_hybrid = None

        if remaining_chunks:
            if self.retriever is None:
                raise RuntimeError(
                    "Documents exist, but the retrieval index is missing."
                )

            replacement_hybrid = (
                self.retriever.hybrid_retriever
                .rebuild_excluding_document(document_id)
            )

            if replacement_hybrid is None:
                raise RuntimeError(
                    "Index rebuild unexpectedly returned no index."
                )

        # Commit changes only after rebuilding has succeeded.
        if self.retriever is not None:
            if replacement_hybrid is None:
                self.retriever = None
            else:
                # Preserve the existing cross-encoder reranker.
                self.retriever.hybrid_retriever = replacement_hybrid

        deleted_record = self.documents.pop(document_id)
        self.chunks = remaining_chunks

        return deleted_record.copy()
