from src.generation.grounding_validator import validate_grounding


source_map = {
    1: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 11,
        "chunk_id": 13,
    },
    2: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 31,
        "chunk_id": 111,
    },
}


source_documents = [
    {
        "text": (
            "An Organizational Profile describes an organization's "
            "current and/or target cybersecurity posture."
        ),
        "metadata": {
            "page": 11,
            "chunk_id": 13,
        },
    },
    {
        "text": (
            "A Target Profile describes the desired cybersecurity "
            "outcomes for an organization."
        ),
        "metadata": {
            "page": 31,
            "chunk_id": 111,
        },
    },
]


answer = (
    "An Organizational Profile describes an organization's "
    "cybersecurity posture. [Source 1] "
    "A Target Profile describes desired outcomes. [Source 2]"
)


result = validate_grounding(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)


print(result)


assert len(result["grounded_citations"]) == 2
assert result["grounded_citations"][0]["source_number"] == 1
assert result["grounded_citations"][1]["source_number"] == 2

assert result["unsupported_citations"] == []