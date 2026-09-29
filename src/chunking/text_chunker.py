"""Text chunking utilities for the RAG pipeline."""

import re


def chunk_documents(
    documents,
    tokenizer,
    chunk_size=200,
    overlap=30,
):
    """Split documents into tokenizer-aligned, paragraph-aware chunks."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0.")

    if overlap < 0:
        raise ValueError("overlap cannot be negative.")

    if overlap >= chunk_size:
        raise ValueError("overlap must be smaller than chunk_size.")

    effective_chunk_size = chunk_size - 20

    if effective_chunk_size <= overlap:
        raise ValueError(
            "chunk_size must leave enough room for the overlap."
        )

    chunks = []

    for document in documents:
        text = document["text"]
        metadata = document["metadata"]

        paragraphs = [
            paragraph.strip()
            for paragraph in text.split("\n\n")
            if paragraph.strip()
        ]

        current_paragraphs = []
        current_tokens = 0

        for paragraph in paragraphs:

            paragraph_tokens = tokenizer.encode(
                paragraph,
                add_special_tokens=False,
            )

            paragraph_token_count = len(paragraph_tokens)

            # Handle paragraphs that are larger than one chunk.
            if paragraph_token_count > chunk_size:

                if current_paragraphs:
                    chunks.append({
                        "text": "\n\n".join(current_paragraphs),
                        "metadata": {
                            **metadata,
                            "chunk_id": len(chunks),
                        },
                    })

                    current_paragraphs = []
                    current_tokens = 0

                step = effective_chunk_size - overlap

                for start in range(
                    0,
                    paragraph_token_count,
                    step,
                ):
                    end = min(
                        start + effective_chunk_size,
                        paragraph_token_count,
                    )

                    token_slice = paragraph_tokens[start:end]

                    if not token_slice:
                        break

                    prefix_tokens = paragraph_tokens[:start]

                    start_text = tokenizer.decode(
                        prefix_tokens,
                        skip_special_tokens=True,
                    )

                    if start > 0:
                        original_start = len(start_text)
                    else:
                        original_start = 0

                    if end < paragraph_token_count:
                        end_tokens = paragraph_tokens[:end]

                        end_text = tokenizer.decode(
                            end_tokens,
                            skip_special_tokens=True,
                        )

                        original_end = len(end_text)
                    else:
                        original_end = len(paragraph)

                    original_chunk = paragraph[
                        original_start:original_end
                    ].strip()

                    if not original_chunk:
                        break

                    # Preserve the original text rather than using
                    # tokenizer.decode() as the final chunk text.
                    chunk_text = original_chunk

                    chunks.append({
                        "text": chunk_text,
                        "metadata": {
                            **metadata,
                            "chunk_id": len(chunks),
                        },
                    })

                continue

            separator_tokens = 0

            if current_paragraphs:
                separator_tokens = len(
                    tokenizer.encode(
                        "\n\n",
                        add_special_tokens=False,
                    )
                )

            required_tokens = (
                current_tokens
                + separator_tokens
                + paragraph_token_count
            )

            if required_tokens <= chunk_size:

                current_paragraphs.append(paragraph)
                current_tokens = required_tokens

                continue

            if current_paragraphs:
                chunks.append({
                    "text": "\n\n".join(current_paragraphs),
                    "metadata": {
                        **metadata,
                        "chunk_id": len(chunks),
                    },
                })

            overlap_paragraphs = []
            overlap_token_count = 0

            for previous_paragraph in reversed(
                current_paragraphs
            ):
                previous_tokens = len(
                    tokenizer.encode(
                        previous_paragraph,
                        add_special_tokens=False,
                    )
                )

                separator_tokens = 0

                if overlap_paragraphs:
                    separator_tokens = len(
                        tokenizer.encode(
                            "\n\n",
                            add_special_tokens=False,
                        )
                    )

                required_overlap = (
                    overlap_token_count
                    + separator_tokens
                    + previous_tokens
                )

                if required_overlap > overlap:
                    break

                overlap_paragraphs.insert(
                    0,
                    previous_paragraph,
                )

                overlap_token_count = required_overlap

            separator_tokens = 0

            if overlap_paragraphs:
                separator_tokens = len(
                    tokenizer.encode(
                        "\n\n",
                        add_special_tokens=False,
                    )
                )

            combined_tokens = (
                overlap_token_count
                + separator_tokens
                + paragraph_token_count
            )

            if combined_tokens <= chunk_size:

                current_paragraphs = (
                    overlap_paragraphs
                    + [paragraph]
                )

                current_tokens = combined_tokens

            else:
                current_paragraphs = [paragraph]
                current_tokens = paragraph_token_count

        if current_paragraphs:
            chunks.append({
                "text": "\n\n".join(current_paragraphs),
                "metadata": {
                    **metadata,
                    "chunk_id": len(chunks),
                },
            })

    return chunks