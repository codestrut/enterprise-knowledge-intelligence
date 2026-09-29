"""Test the document chunking module."""

import tiktoken

from src.ingestion.pdf_loader import load_pdf
from src.chunking.text_chunker import chunk_documents


pdf_path = "data/raw/nist_csf_2.0.pdf"

documents = load_pdf(pdf_path)

chunks = chunk_documents(documents)

encoder = tiktoken.get_encoding("cl100k_base")

print(f"Number of pages: {len(documents)}")
print(f"Number of chunks: {len(chunks)}")

for number, chunk in enumerate(chunks[30:35], start=30):
    token_count = len(encoder.encode(chunk["text"]))

    print(f"\n{'=' * 60}")
    print(f"Chunk ID: {chunk['metadata']['chunk_id']}")
    print(f"Page: {chunk['metadata']['page']}")
    print(f"Tokens: {token_count}")
    print(f"{'=' * 60}")
    print(chunk["text"])