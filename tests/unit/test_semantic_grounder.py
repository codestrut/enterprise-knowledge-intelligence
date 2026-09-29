from src.generation.semantic_grounder import SemanticGrounder


grounder = SemanticGrounder()


evidence = (
    "An Organizational Profile describes an organization's "
    "current and/or target cybersecurity posture."
)


tests = [
    {
        "name": "Supported claim",
        "claim": (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture."
        ),
    },
    {
        "name": "Contradictory claim",
        "claim": (
            "An Organizational Profile is used to manage an "
            "organization's financial budget."
        ),
    },
    {
        "name": "Unrelated claim",
        "claim": (
            "The organization operates offices in five different countries."
        ),
    },
]


for test in tests:

    result = grounder.check_claim(
        claim=test["claim"],
        evidence=evidence,
    )

    print("\n" + "=" * 80)
    print(test["name"])
    print("=" * 80)
    print("Claim:", test["claim"])
    print("Result:", result)