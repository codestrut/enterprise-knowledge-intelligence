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

    # NIST SP 800-53 can be split by PDF text extraction as "SP 800-5 3"
    # or "SP 800- 5 3". Normalize only this known publication identifier;
    # do not join arbitrary spaced digits across unrelated content.
    text = re.sub(
        r"\bSP\s+800\s*-\s*5\s+3\b",
        "SP 800-53",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()