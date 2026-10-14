#!/usr/bin/env python3
"""Validate actual chunk token lengths against the configured embedding model.

Run from the EKIP repository root after applying the token-safe chunker patch.
This does not call the LLM provider or load the reranker/NLI CrossEncoders.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from src.chunking.text_chunker import chunk_documents
from src.embeddings.embedder import Embedder
from src.ingestion.pdf_loader import load_pdf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", nargs="?", default="data/raw/nist_csf_2.0.pdf")
    parser.add_argument("--chunk-size", type=int, default=200)
    parser.add_argument("--overlap", type=int, default=30)
    args = parser.parse_args()

    document_path = Path(args.document).expanduser().resolve()
    if not document_path.is_file():
        parser.error(f"Document not found: {document_path}")

    embedder = Embedder()
    tokenizer = embedder.model.tokenizer
    model_max_length = getattr(embedder.model, "max_seq_length", None)
    pages = load_pdf(str(document_path))
    chunks = chunk_documents(
        pages,
        tokenizer=tokenizer,
        chunk_size=args.chunk_size,
        overlap=args.overlap,
    )

    if not chunks:
        print("No chunks were generated.")
        return 1

    records = []
    for index, chunk in enumerate(chunks):
        token_count = len(
            tokenizer.encode(chunk["text"], add_special_tokens=True)
        )
        records.append((token_count, index, chunk))

    maximum = max(item[0] for item in records)
    over_limit = (
        [] if model_max_length is None
        else [item for item in records if item[0] > model_max_length]
    )

    print(f"Document: {document_path.name}")
    print(f"Pages extracted: {len(pages)}")
    print(f"Chunks generated: {len(chunks)}")
    print(f"Embedding model max sequence length: {model_max_length}")
    print(f"Maximum chunk tokens including special tokens: {maximum}")
    print(f"Chunks over model limit: {len(over_limit)}")

    for token_count, index, chunk in over_limit[:10]:
        metadata = chunk.get("metadata", {})
        print(
            f"OVER LIMIT: chunk_index={index}, tokens={token_count}, "
            f"page={metadata.get('page')}, chunk_id={metadata.get('chunk_id')}"
        )

    if model_max_length is not None and over_limit:
        return 1

    print("PASS: all generated chunks fit the configured embedding model limit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
