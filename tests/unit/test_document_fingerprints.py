from pathlib import Path

from src.api.document_fingerprints import (
    find_duplicate_document,
    sha256_file,
)


def test_sha256_file_is_stable_and_content_based(tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    first.write_bytes(b"%PDF-same bytes")
    second.write_bytes(b"%PDF-same bytes")

    assert sha256_file(first) == sha256_file(second)


def test_duplicate_is_found_for_identical_uploaded_content(tmp_path):
    first = tmp_path / "existing.pdf"
    new_upload = tmp_path / "incoming.pdf"
    first.write_bytes(b"%PDF-identical")
    new_upload.write_bytes(b"%PDF-identical")
    documents = {
        "doc-1": {
            "document_id": "doc-1",
            "filename": "existing.pdf",
            "source": str(first),
        }
    }

    match = find_duplicate_document(
        sha256_file(new_upload), documents, tmp_path
    )

    assert match is not None
    assert match["document_id"] == "doc-1"


def test_different_content_is_not_duplicate(tmp_path):
    first = tmp_path / "existing.pdf"
    new_upload = tmp_path / "incoming.pdf"
    first.write_bytes(b"%PDF-old")
    new_upload.write_bytes(b"%PDF-new")
    documents = {
        "doc-1": {"document_id": "doc-1", "source": str(first)}
    }

    assert find_duplicate_document(
        sha256_file(new_upload), documents, tmp_path
    ) is None


def test_sources_outside_upload_directory_are_ignored(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    external = tmp_path / "external.pdf"
    incoming = uploads / "incoming.pdf"
    external.write_bytes(b"%PDF-same")
    incoming.write_bytes(b"%PDF-same")
    documents = {
        "external-doc": {
            "document_id": "external-doc",
            "source": str(external),
            "sha256": sha256_file(external),
        }
    }

    assert find_duplicate_document(
        sha256_file(incoming), documents, uploads
    ) is None


def test_saved_hash_is_reused_for_existing_manifest_entry(tmp_path, monkeypatch):
    import src.api.document_fingerprints as fingerprints

    existing = tmp_path / "existing.pdf"
    incoming = tmp_path / "incoming.pdf"
    existing.write_bytes(b"%PDF-same")
    incoming.write_bytes(b"%PDF-same")
    uploaded_digest = sha256_file(incoming)
    documents = {
        "doc-1": {
            "document_id": "doc-1",
            "source": str(existing),
            "sha256": uploaded_digest,
        }
    }

    original_sha256_file = fingerprints.sha256_file

    def forbid_existing_file_rehash(path):
        if Path(path) == existing:
            raise AssertionError("Stored manifest digest should be reused")
        return original_sha256_file(path)

    monkeypatch.setattr(fingerprints, "sha256_file", forbid_existing_file_rehash)
    match = find_duplicate_document(uploaded_digest, documents, tmp_path)

    assert match is not None
    assert match["document_id"] == "doc-1"


def test_duplicate_is_found_from_document_id_when_no_source_is_stored(tmp_path):
    existing = tmp_path / "doc-1.pdf"
    incoming = tmp_path / "incoming.pdf"
    existing.write_bytes(b"%PDF-same")
    incoming.write_bytes(b"%PDF-same")
    documents = {
        "doc-1": {
            "document_id": "doc-1",
            "stored_filename": "doc-1.pdf",
            "status": "indexed",
        }
    }

    match = find_duplicate_document(sha256_file(incoming), documents, tmp_path)

    assert match is not None
    assert match["document_id"] == "doc-1"


def test_legacy_absolute_source_outside_uploads_falls_back_to_document_id(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "doc-1.pdf").write_bytes(b"%PDF-same")
    incoming = uploads / "incoming.pdf"
    incoming.write_bytes(b"%PDF-same")
    documents = {
        "doc-1": {
            "document_id": "doc-1",
            "source": "/Users/someone/project/data/uploads/doc-1.pdf",
        }
    }

    match = find_duplicate_document(sha256_file(incoming), documents, uploads)

    assert match is not None
    assert match["document_id"] == "doc-1"


def test_failed_and_pending_records_are_never_duplicates(tmp_path):
    (tmp_path / "doc-1.pdf").write_bytes(b"%PDF-same")
    incoming = tmp_path / "incoming.pdf"
    incoming.write_bytes(b"%PDF-same")

    for status in ("failed", "pending"):
        documents = {"doc-1": {"document_id": "doc-1", "status": status}}
        assert find_duplicate_document(
            sha256_file(incoming), documents, tmp_path
        ) is None
