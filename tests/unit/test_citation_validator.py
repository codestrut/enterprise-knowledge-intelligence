from src.generation.citation_validator import validate_citations


source_map = {
    1: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 11,
        "chunk_id": 13,
    },
    5: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 31,
        "chunk_id": 43,
    },
}


answer = (
    "An Organizational Profile describes an organization's "
    "current and target cybersecurity posture. "
    "[Source 1][Source 99]"
)


result = validate_citations(
    answer=answer,
    source_map=source_map,
)


print(result)