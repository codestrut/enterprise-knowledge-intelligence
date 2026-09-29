from src.generation.grounding_evaluator import GroundingEvaluator


source_map = {
    1: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 11,
        "chunk_id": 13,
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
]


tests = [
    {
        "name": "Supported claim",
        "answer": (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture. [Source 1]"
        ),
    },
    {
        "name": "Contradictory claim",
        "answer": (
            "An Organizational Profile is used to manage an "
            "organization's financial budget. [Source 1]"
        ),
    },
    {
        "name": "Unrelated claim",
        "answer": (
            "The organization operates offices in five different "
            "countries. [Source 1]"
        ),
    },
    
    {
        "name": "Compound claim",
        "answer": (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture and the organization "
            "operates offices in five different countries. [Source 1]"
        ),
    },
]




evaluator = GroundingEvaluator()


for test in tests:

    results = evaluator.evaluate(
        answer=test["answer"],
        source_map=source_map,
        source_documents=source_documents,
    )

    print("\n" + "=" * 80)
    print(test["name"])
    print("=" * 80)

    for result in results:

        print("\nCLAIM:")
        print(result["claim"])

        print("\nSTATUS:")
        print(result["status"])

        print("\nSOURCE EVALUATIONS:")

        for source in result["sources"]:
            print(source)