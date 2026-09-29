from src.generation.grounding_validator import validate_grounding


source_map = {
    1: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 11,
        "chunk_id": 13,
    }
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
    }
]


answer = (
    "An Organizational Profile contains the organization's "
    "financial budget for cybersecurity activities. [Source 1]"
)


result = validate_grounding(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)


print(result)