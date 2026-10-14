"""Helpers for persisted and public document records.

The manifest must stay portable (no absolute server paths), and API responses
must not reveal where files live on the server. Uploaded PDFs are always
stored as ``<document_id>.pdf`` inside the upload directory, so the path is
derived from the document ID at runtime instead of being persisted.
"""

from pathlib import Path

STORED_SUFFIX = ".pdf"

# Fields kept internally or on disk but never returned to API clients.
_PRIVATE_FIELDS = frozenset({"source", "stored_filename"})


def resolve_stored_path(upload_directory, document_id):
    """Return the stored PDF path for a document ID, confined to the uploads.

    Raises ValueError for IDs that are empty or contain path components.
    """
    name = f"{document_id}{STORED_SUFFIX}"

    if not document_id or Path(name).name != name or name.startswith("."):
        raise ValueError("Invalid document ID.")

    root = Path(upload_directory).resolve()
    path = (root / name).resolve()

    if not path.is_relative_to(root):
        raise ValueError("Invalid document ID.")

    return path


def public_record(record):
    """Return a copy of a document record that is safe to send to clients."""
    return {
        key: value
        for key, value in record.items()
        if key not in _PRIVATE_FIELDS
    }


def manifest_record(document_id, record):
    """Return the persisted form of a record: portable, no absolute path."""
    persisted = {
        key: value
        for key, value in record.items()
        if key != "source"
    }
    persisted["document_id"] = document_id
    persisted["stored_filename"] = f"{document_id}{STORED_SUFFIX}"
    return persisted
