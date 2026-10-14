"""PDF document ingestion utilities."""

from pypdf import PdfReader

from src.ingestion.text_cleaner import clean_text


def load_pdf(file_path):
    reader = PdfReader(file_path)

    documents = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = clean_text(page.extract_text() or "")

        documents.append({
            "text": text,
            "metadata": {
                "source": file_path,
                "page": page_number
            }
        })

    return documents