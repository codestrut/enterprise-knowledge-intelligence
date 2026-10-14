import re

import pytest

from src.chunking.token_safe_splitter import split_text_by_token_offsets
from src.chunking.text_chunker import chunk_documents


class WordOffsetTokenizer:
    """Small deterministic tokenizer fixture with exact character offsets."""

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        matches = list(re.finditer(r"\S+", text))
        result = {"input_ids": list(range(len(matches)))}
        if return_offsets_mapping:
            result["offset_mapping"] = [(m.start(), m.end()) for m in matches]
        return result

    def encode(self, text, add_special_tokens=False):
        return list(range(len(re.findall(r"\S+", text))))

    def decode(self, ids, skip_special_tokens=True, clean_up_tokenization_spaces=False):
        # Fallback fixture only; fast offset path is tested separately.
        return " ".join(f"w{idx}" for idx in ids)


class DecodeOnlyTokenizer:
    """Tokenizer fixture without offset mappings to test fallback behaviour."""

    def encode(self, text, add_special_tokens=False):
        return list(range(len(re.findall(r"\S+", text))))

    def decode(self, ids, skip_special_tokens=True, clean_up_tokenization_spaces=False):
        return " ".join(f"token{idx}" for idx in ids)


def test_long_text_is_split_to_token_windows_and_preserves_source_text():
    tokenizer = WordOffsetTokenizer()
    text = " ".join(f"word{i}" for i in range(250))

    chunks = split_text_by_token_offsets(
        text,
        tokenizer,
        max_tokens=180,
        overlap=30,
    )

    assert len(chunks) == 2
    assert all(len(tokenizer.encode(chunk)) <= 180 for chunk in chunks)
    assert chunks[0].split()[0] == "word0"
    assert chunks[-1].split()[-1] == "word249"
    # The second chunk starts where a 30-token overlap begins.
    assert chunks[1].split()[0] == "word150"


def test_short_text_is_returned_unchanged_except_outer_whitespace():
    tokenizer = WordOffsetTokenizer()
    text = "  first second third  "

    assert split_text_by_token_offsets(text, tokenizer, 10) == [
        "first second third"
    ]


def test_empty_text_returns_no_chunks():
    assert split_text_by_token_offsets("  ", WordOffsetTokenizer(), 10) == []


def test_invalid_limits_raise_clear_errors():
    tokenizer = WordOffsetTokenizer()
    with pytest.raises(ValueError):
        split_text_by_token_offsets("alpha beta", tokenizer, 0)
    with pytest.raises(ValueError):
        split_text_by_token_offsets("alpha beta", tokenizer, 10, overlap=10)


def test_falls_back_to_token_ids_when_offsets_are_unavailable():
    tokenizer = DecodeOnlyTokenizer()
    text = " ".join(f"original{i}" for i in range(250))

    chunks = split_text_by_token_offsets(text, tokenizer, 100, overlap=10)

    assert len(chunks) == 3
    assert all(len(tokenizer.encode(chunk)) <= 100 for chunk in chunks)


def test_chunk_documents_never_creates_oversized_long_paragraph_chunks():
    tokenizer = WordOffsetTokenizer()
    text = " ".join(f"word{i}" for i in range(738))
    documents = [{"text": text, "metadata": {"page": 1, "document_id": "doc-1"}}]

    chunks = chunk_documents(
        documents,
        tokenizer=tokenizer,
        chunk_size=200,
        overlap=30,
    )

    assert len(chunks) > 1
    assert all(len(tokenizer.encode(chunk["text"])) <= 180 for chunk in chunks)
    assert [chunk["metadata"]["chunk_id"] for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk["metadata"]["document_id"] == "doc-1" for chunk in chunks)
