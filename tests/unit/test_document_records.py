import pytest

from src.api.document_records import (
    manifest_record,
    public_record,
    resolve_stored_path,
)


def test_resolve_stored_path_stays_inside_the_upload_directory(tmp_path):
    path = resolve_stored_path(tmp_path, "abc-123")

    assert path == (tmp_path / "abc-123.pdf").resolve()


def test_resolve_stored_path_rejects_ids_with_path_components(tmp_path):
    for bad_id in ("", None, "../evil", "a/b", "/etc/passwd", "..", ".hidden"):
        with pytest.raises(ValueError):
            resolve_stored_path(tmp_path, bad_id)


def test_public_record_hides_server_side_fields_without_mutating_input():
    record = {
        "document_id": "doc-1",
        "filename": "NIST Test.pdf",
        "source": "/Users/someone/data/uploads/doc-1.pdf",
        "stored_filename": "doc-1.pdf",
        "status": "indexed",
        "chunk_count": 3,
    }

    public = public_record(record)

    assert public == {
        "document_id": "doc-1",
        "filename": "NIST Test.pdf",
        "status": "indexed",
        "chunk_count": 3,
    }
    assert "source" in record and "stored_filename" in record


def test_manifest_record_is_portable_and_has_no_absolute_path():
    record = {
        "document_id": "doc-1",
        "filename": "NIST Test.pdf",
        "source": "/Users/someone/data/uploads/doc-1.pdf",
        "status": "indexed",
        "sha256": "abc",
    }

    persisted = manifest_record("doc-1", record)

    assert "source" not in persisted
    assert persisted["stored_filename"] == "doc-1.pdf"
    assert persisted["document_id"] == "doc-1"
    assert persisted["filename"] == "NIST Test.pdf"
    assert persisted["sha256"] == "abc"
    assert "/Users/" not in repr(persisted)
    assert "source" in record  # input is not mutated
