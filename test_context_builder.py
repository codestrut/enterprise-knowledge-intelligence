"""Test the context builder."""

from src.generation.context_builder import build_context


documents = [
    {
        "text": "An Organizational Profile describes an organization's current and target cybersecurity posture.",
        "metadata": {
            "source": "data/raw/nist_csf_2.0.pdf",
            "page": 12,
            "chunk_id": 13,
        },
        "score": 0.91,
    },
    {
        "text": "Organizations can use Profiles to describe their cybersecurity posture.",
        "metadata": {
            "source": "data/raw/nist_csf_2.0.pdf",
            "page": 13,
            "chunk_id": 14,
        },
        "score": 0.87,
    },
]


context = build_context(documents)

print(context)
