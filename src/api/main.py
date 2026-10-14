
"""FastAPI application for the Enterprise Knowledge Intelligence Platform."""

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from threading import RLock
from uuid import uuid4

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from src.api.document_fingerprints import (
    find_duplicate_document,
    sha256_file,
)
from src.knowledge_base import KnowledgeBase
from src.rag_pipeline import RAGPipeline


logger = logging.getLogger(__name__)

BASE_DIRECTORY = Path(__file__).resolve().parents[2]
UPLOAD_DIRECTORY = BASE_DIRECTORY / "data" / "uploads"
MANIFEST_PATH = BASE_DIRECTORY / "data" / "documents_manifest.json"

UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

knowledge_base = KnowledgeBase()
pipeline = RAGPipeline(knowledge_base=knowledge_base)

# Protect document indexing, deletion, and queries from concurrent changes.
knowledge_base_lock = RLock()


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
        description="Number of chunks to retrieve.",
    )


def _read_manifest():
    """Load persisted document records."""
    if not MANIFEST_PATH.exists():
        return {}

    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as source:
            data = json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Cannot read document manifest: {MANIFEST_PATH}"
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError("Document manifest must contain a JSON object.")

    documents = data.get("documents", {})
    if not isinstance(documents, dict):
        raise RuntimeError("Manifest 'documents' must be a JSON object.")

    return documents


def _write_manifest(documents):
    """Atomically persist document records."""
    temporary_path = MANIFEST_PATH.with_suffix(".json.tmp")

    payload = {"documents": documents}

    try:
        with temporary_path.open("w", encoding="utf-8") as destination:
            json.dump(payload, destination, indent=2, ensure_ascii=False)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())

        os.replace(temporary_path, MANIFEST_PATH)
    finally:
        temporary_path.unlink(missing_ok=True)


def _set_original_filename(document_id, filename):
    """Keep the client-provided filename in the document and chunk metadata."""
    record = knowledge_base.documents[document_id]
    record["filename"] = filename

    for chunk in knowledge_base.chunks:
        metadata = chunk.get("metadata", {})
        if metadata.get("document_id") == document_id:
            metadata["filename"] = filename


def _bootstrap_manifest():
    """Register existing uploaded PDFs when no manifest exists.

    Legacy files may not retain their original client-provided filenames.
    In that case, the stored filename is used as the best available value.
    """
    documents = {}

    for path in sorted(UPLOAD_DIRECTORY.glob("*.pdf")):
        document_id = path.stem

        documents[document_id] = {
            "document_id": document_id,
            "filename": path.name,
            "source": str(path.resolve()),
            "status": "pending",
        }

    _write_manifest(documents)
    return documents


def _restore_knowledge_base():
    """Rebuild in-memory indexes from persisted manifest records."""
    if not MANIFEST_PATH.exists():
        documents = _bootstrap_manifest()
    else:
        documents = _read_manifest()

    restored_records = {}
    failed_documents = []

    for document_id, saved_record in documents.items():
        try:
            source_path = Path(saved_record["source"]).resolve()
            filename = saved_record.get("filename", source_path.name)

            # Never index arbitrary external paths from a manifest.
            if not source_path.is_relative_to(UPLOAD_DIRECTORY.resolve()):
                raise ValueError("Document path is outside the upload directory.")

            if not source_path.is_file():
                raise FileNotFoundError(
                    f"Uploaded PDF is missing: {source_path}"
                )

            record = knowledge_base.add_pdf(
                file_path=source_path,
                document_id=document_id,
            )

            _set_original_filename(document_id, filename)

            record = knowledge_base.documents[document_id]
            record["filename"] = filename
            record["status"] = "indexed"
            record["sha256"] = saved_record.get("sha256") or sha256_file(source_path)
            knowledge_base.documents[document_id]["sha256"] = record["sha256"]
            restored_records[document_id] = record.copy()

            logger.info(
                "Restored document %s (%s), %d chunks",
                document_id,
                filename,
                record["chunk_count"],
            )

        except Exception as exc:
            failed_documents.append(document_id)
            logger.exception(
                "Could not restore document %s: %s",
                document_id,
                exc,
            )

    # Persist only successfully restored documents. Failed records are
    # logged and excluded from the active manifest rather than reported
    # as indexed when their indexes do not exist.
    _write_manifest(restored_records)

    if failed_documents:
        logger.error(
            "Startup restoration failed for %d document(s): %s",
            len(failed_documents),
            ", ".join(failed_documents),
        )

    logger.info(
        "Knowledge base startup complete: %d document(s), %d chunk(s)",
        len(knowledge_base.documents),
        len(knowledge_base.chunks),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Restore document indexes before accepting requests."""
    with knowledge_base_lock:
        _restore_knowledge_base()

    yield


app = FastAPI(
    title="Enterprise Knowledge Intelligence Platform",
    version="1.2.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """Return API and knowledge-base status."""
    with knowledge_base_lock:
        return {
            "status": "ok",
            "document_count": len(knowledge_base.documents),
            "chunk_count": len(knowledge_base.chunks),
            "manifest_exists": MANIFEST_PATH.exists(),
        }


@app.post("/documents", status_code=201)
def upload_document(file: UploadFile = File(...)):
    """Upload, index, and persist a PDF document."""
    filename = Path(file.filename or "").name

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are supported.",
        )

    document_id = str(uuid4())
    stored_path = UPLOAD_DIRECTORY / f"{document_id}.pdf"

    try:
        total_bytes = 0
        header = b""

        with stored_path.open("wb") as destination:
            while chunk := file.file.read(1024 * 1024):
                if not header:
                    header = chunk[:5]

                total_bytes += len(chunk)

                if total_bytes > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF exceeds the 25 MB upload limit.",
                    )

                destination.write(chunk)

        if header != b"%PDF-":
            raise HTTPException(
                status_code=400,
                detail="Uploaded file is not a valid PDF.",
            )

        uploaded_sha256 = sha256_file(stored_path)

        with knowledge_base_lock:
            existing_documents = _read_manifest()
            duplicate_record = find_duplicate_document(
                file_digest=uploaded_sha256,
                documents=existing_documents,
                upload_directory=UPLOAD_DIRECTORY,
            )
            if duplicate_record is not None:
                stored_path.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Identical PDF content is already indexed.",
                        "existing_document": duplicate_record,
                    },
                )

            record = knowledge_base.add_pdf(
                file_path=stored_path,
                document_id=document_id,
            )

            _set_original_filename(document_id, filename)

            record = knowledge_base.documents[document_id]
            record["filename"] = filename
            record["status"] = "indexed"
            record["sha256"] = uploaded_sha256

            updated_documents = {
                **existing_documents,
                document_id: record.copy(),
            }

            try:
                _write_manifest(updated_documents)
            except Exception:
                # Roll back the in-memory index if persistence fails.
                knowledge_base.delete_document(document_id)
                raise

        return {
            "message": "Document indexed and registered successfully.",
            "document": record.copy(),
        }

    except HTTPException:
        stored_path.unlink(missing_ok=True)
        raise

    except (ValueError, FileNotFoundError) as exc:
        stored_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception:
        stored_path.unlink(missing_ok=True)
        logger.exception("Document upload or indexing failed.")
        raise HTTPException(
            status_code=500,
            detail="Document upload or indexing failed.",
        )

    finally:
        file.file.close()


@app.get("/documents")
def list_documents():
    """List documents currently indexed in memory."""
    with knowledge_base_lock:
        documents = knowledge_base.list_documents()

    return {
        "count": len(documents),
        "documents": documents,
    }


@app.post("/query")
def query(request: QueryRequest):
    """Answer a question using the current knowledge base."""
    with knowledge_base_lock:
        try:
            return pipeline.query(
                question=request.question,
                top_k=request.top_k,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            ) from exc


@app.delete("/documents/{document_id}")
def delete_document(document_id: str):
    """Remove a document from the indexes, manifest, and upload directory."""
    with knowledge_base_lock:
        record = knowledge_base.documents.get(document_id)

        if record is None:
            raise HTTPException(
                status_code=404,
                detail=f"Document not found: {document_id}",
            )

        source_path = Path(record["source"]).resolve()
        upload_directory = UPLOAD_DIRECTORY.resolve()

        if not source_path.is_relative_to(upload_directory):
            raise HTTPException(
                status_code=400,
                detail="Document source is outside the upload directory.",
            )

        current_manifest = _read_manifest()
        updated_manifest = {
            key: value
            for key, value in current_manifest.items()
            if key != document_id
        }

        # Persist the intended deletion first. If writing fails, the
        # active knowledge base remains unchanged.
        try:
            _write_manifest(updated_manifest)
        except Exception as exc:
            logger.exception("Could not update manifest during deletion.")
            raise HTTPException(
                status_code=500,
                detail="Could not persist document deletion.",
            ) from exc

        try:
            deleted_record = knowledge_base.delete_document(document_id)
        except Exception as exc:
            # Restore the prior manifest if in-memory deletion fails.
            try:
                _write_manifest(current_manifest)
            except Exception:
                logger.exception("Could not restore manifest after delete failure.")

            logger.exception("Could not remove document from active indexes.")
            raise HTTPException(
                status_code=500,
                detail="Could not remove document from active indexes.",
            ) from exc

        file_deleted = False
        cleanup_required = False

        try:
            source_path.unlink(missing_ok=True)
            file_deleted = True
        except OSError:
            cleanup_required = True
            logger.exception(
                "Document was logically deleted but its PDF could not be removed."
            )

        return {
            "message": "Document removed from the active knowledge base.",
            "document_id": document_id,
            "filename": deleted_record["filename"],
            "chunks_removed": deleted_record["chunk_count"],
            "file_deleted": file_deleted,
            "cleanup_required": cleanup_required,
        }
