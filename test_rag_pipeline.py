from src.rag_pipeline import RAGPipeline


DOCUMENT_PATH = "data/raw/nist_csf_2.0.pdf"


pipeline = RAGPipeline(
    document_path=DOCUMENT_PATH
)


question = "What is an Organizational Profile?"


result = pipeline.query(
    question=question,
    top_k=5,
)


print("=" * 80)
print("QUESTION")
print("=" * 80)
print(result["question"])


print("\n" + "=" * 80)
print("ANSWER")
print("=" * 80)
print(result["answer"])


print("\n" + "=" * 80)
print("REFUSED")
print("=" * 80)
print(result["refused"])


print("\n" + "=" * 80)
print("CITATIONS")
print("=" * 80)
print(result["citations"])


print("\n" + "=" * 80)
print("INVALID CITATIONS")
print("=" * 80)
print(result["invalid_citations"])


print("\n" + "=" * 80)
print("EVIDENCE GATE")
print("=" * 80)
print(result["evidence"])


print("\n" + "=" * 80)
print("GROUNDING EVALUATION")
print("=" * 80)


for evaluation in result["grounding"]:

    print("\nCLAIM:")
    print(evaluation["claim"])

    print("\nOVERALL STATUS:")
    print(evaluation["status"])

    print("\nATOMIC CLAIMS:")

    for index, atomic_claim in enumerate(
        evaluation["atomic_claims"],
        start=1,
    ):

        print(f"\n  Atomic Claim {index}:")
        print(f"  {atomic_claim['claim']}")

        print(
            f"\n  Status: "
            f"{atomic_claim['status']}"
        )

        print("\n  SOURCE EVALUATIONS:")

        for source in atomic_claim["sources"]:

            print(
                f"    Source "
                f"{source['source_number']}: "
                f"{source['label']}"
            )

            if "reason" in source:
                print(
                    f"    Reason: "
                    f"{source['reason']}"
                )

            if "evidence" in source:

                for evidence in source["evidence"]:

                    print(
                        f"    Evidence score: "
                        f"{evidence['evidence_score']}"
                    )

                    print(
                        f"    NLI label: "
                        f"{evidence['label']}"
                    )

                    print(
                        f"    Evidence: "
                        f"{evidence['evidence']}"
                    )


print("\n" + "=" * 80)
print("RETRIEVED SOURCES")
print("=" * 80)


for rank, source in enumerate(
    result["sources"],
    start=1,
):

    metadata = source["metadata"]

    print(
        f"\nSource {rank}"
    )

    print(
        f"Page: "
        f"{metadata.get('page')}"
    )

    print(
        f"Chunk: "
        f"{metadata.get('chunk_id')}"
    )

    print(
        f"Score: "
        f"{source['score']}"
    )

    print(
        f"Text:\n"
        f"{source['text']}"
    )


print("\n" + "=" * 80)
print("PIPELINE TEST COMPLETE")
print("=" * 80)