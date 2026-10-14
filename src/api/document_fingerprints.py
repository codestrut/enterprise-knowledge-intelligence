"""Content fingerprint helpers for idempotent PDF ingestion."""

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    """Return a streaming SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_duplicate_document(
    file_digest: str,
    documents: dict,
    upload_directory: str | Path,
) -> dict | None:
    """Find an existing uploaded document with identical bytes.

    Only files inside the configured upload directory are considered. Older
    manifest records without a stored digest are fingerprinted on demand.
    The returned record is copied so callers cannot mutate the manifest via
    this helper.
    """
    allowed_root = Path(upload_directory).expanduser().resolve()

    for document_id, record in documents.items():
        source_value = record.get("source")
        if not source_value:
            continue

        source_path = Path(source_value).expanduser().resolve()
        if not source_path.is_relative_to(allowed_root):
            continue
        if not source_path.is_file():
            continue

        try:
            existing_digest = record.get("sha256") or sha256_file(source_path)
        except OSError:
            # A missing/unreadable old file must not block a valid upload.
            continue

        if existing_digest == file_digest:
            return dict(record, document_id=record.get("document_id", document_id))

    return None
