"""PDF document ingestion utilities."""

from pypdf import PdfReader


def load_pdf(file_path):
    reader = PdfReader(file_path)

    documents = []

    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text()

        documents.append({
            "text": text,
            "metadata": {
                "source": file_path,
                "page": page_number
            }
        })

    return documents