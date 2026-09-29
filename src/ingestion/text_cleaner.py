"""Text cleaning utilities for extracted documents."""

import re


def clean_text(text):
    """Normalize whitespace and common PDF extraction artifacts."""

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    text = "\n".join(
        line.rstrip()
        for line in text.split("\n")
    )

    text = re.sub(
        r"\b([A-Z]{2})\s*\.\s*([A-Z]{2})\s*-\s*(\d{2})\b",
        r"\1.\2-\3",
        text,
    )

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()