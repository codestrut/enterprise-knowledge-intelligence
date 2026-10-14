"""Token-bounded, source-preserving splitting for long paragraphs.

The fast-tokenizer path uses character offset mappings to slice the original
text. This avoids deriving source character offsets from decoded token IDs,
which can drift when the tokenizer normalizes whitespace or Unicode. A
fallback uses token-ID decoding for tokenizers without offset mappings.
"""
from __future__ import annotations

from typing import Any


def _encoded_ids(encoded: Any) -> list[int] | None:
    """Extract one unbatched input_ids list from a tokenizer result."""
    try:
        ids = encoded["input_ids"]
    except (KeyError, TypeError):
        return None
    # Tokenizers may return tensors/arrays; this function intentionally avoids
    # adding a torch/numpy dependency just for simple shape normalization.
    if hasattr(ids, "tolist"):
        ids = ids.tolist()
    if isinstance(ids, tuple):
        ids = list(ids)
    if not isinstance(ids, list):
        return None
    if ids and isinstance(ids[0], list):
        if len(ids) != 1:
            return None
        ids = ids[0]
    return ids if all(isinstance(token, int) for token in ids) else None


def _offsets(encoded: Any) -> list[tuple[int, int]] | None:
    try:
        offsets = encoded["offset_mapping"]
    except (KeyError, TypeError):
        return None
    if hasattr(offsets, "tolist"):
        offsets = offsets.tolist()
    if isinstance(offsets, tuple):
        offsets = list(offsets)
    if not isinstance(offsets, list):
        return None
    if offsets and isinstance(offsets[0], list) and offsets[0] and isinstance(offsets[0][0], (list, tuple)):
        if len(offsets) != 1:
            return None
        offsets = offsets[0]
    try:
        result = [(int(pair[0]), int(pair[1])) for pair in offsets]
    except (TypeError, ValueError, IndexError):
        return None
    return result


def _decode(tokenizer: Any, token_ids: list[int]) -> str:
    """Decode token IDs without optional whitespace cleanup when supported."""
    try:
        return tokenizer.decode(
            token_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )
    except TypeError:
        return tokenizer.decode(token_ids, skip_special_tokens=True)


def split_text_by_token_offsets(
    text: str,
    tokenizer: Any,
    max_tokens: int,
    overlap: int = 0,
) -> list[str]:
    """Split ``text`` into token-bounded chunks with a token overlap.

    ``max_tokens`` refers to tokens produced by ``tokenizer.encode`` without
    special tokens. If the tokenizer exposes valid offset mappings, returned
    chunks are slices of the original string. If offsets aren't supported,
    windows are decoded from their token IDs instead; this still prevents a
    single output chunk from including an unbounded token window.
    """
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    if max_tokens <= 0:
        raise ValueError("max_tokens must be greater than zero")
    if overlap < 0 or overlap >= max_tokens:
        raise ValueError("overlap must be non-negative and smaller than max_tokens")

    if not text.strip():
        return []

    encode = getattr(tokenizer, "encode", None)
    if not callable(encode):
        raise TypeError("tokenizer must expose encode()")

    token_ids = list(encode(text, add_special_tokens=False))
    if not token_ids:
        return []
    if len(token_ids) <= max_tokens:
        return [text.strip()]

    step = max_tokens - overlap

    # Preferred path: preserve source substrings using fast tokenizer offsets.
    call = tokenizer if callable(tokenizer) else None
    if call is not None:
        try:
            encoded = call(
                text,
                add_special_tokens=False,
                return_offsets_mapping=True,
            )
            offset_ids = _encoded_ids(encoded)
            offsets = _offsets(encoded)
            if (
                offset_ids is not None
                and offsets is not None
                and len(offset_ids) == len(token_ids) == len(offsets)
            ):
                pieces: list[str] = []
                start = 0
                while start < len(token_ids):
                    end = min(start + max_tokens, len(token_ids))
                    char_start = offsets[start][0]
                    char_end = offsets[end - 1][1]
                    if char_start < 0 or char_end > len(text) or char_end <= char_start:
                        pieces = []
                        break
                    piece = text[char_start:char_end].strip()
                    if not piece:
                        pieces = []
                        break
                    pieces.append(piece)
                    if end >= len(token_ids):
                        break
                    start += step
                if pieces:
                    return pieces
        except (NotImplementedError, TypeError, ValueError, KeyError):
            # Some slow tokenizers don't expose offsets. Fall back below.
            pass

    # Fallback: split the token-ID list itself, never infer character offsets
    # from a decoded prefix and apply those offsets to the original text.
    pieces = []
    for start in range(0, len(token_ids), step):
        piece = _decode(tokenizer, token_ids[start : start + max_tokens]).strip()
        if piece:
            pieces.append(piece)
        if start + max_tokens >= len(token_ids):
            break

    if not pieces:
        raise ValueError("Tokenizer could not produce non-empty bounded chunks")
    return pieces
