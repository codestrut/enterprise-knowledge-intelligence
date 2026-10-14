"""Verify PDF extraction uses the text cleaner before indexing."""

from src.ingestion import pdf_loader


class _FakePage:
    def extract_text(self):
        return "Controls from SP 800-5 3."


class _FakeReader:
    def __init__(self, _path):
        self.pages = [_FakePage()]


def test_load_pdf_normalizes_known_extraction_artifact(monkeypatch):
    monkeypatch.setattr(pdf_loader, "PdfReader", _FakeReader)

    documents = pdf_loader.load_pdf("fixture.pdf")

    assert documents[0]["text"] == "Controls from SP 800-53."
    assert documents[0]["metadata"]["page"] == 1
