"""Test the complete RAG pipeline."""

from src.rag_pipeline import RAGPipeline


pipeline = RAGPipeline(
    "data/raw/nist_csf_2.0.pdf"
)


result = pipeline.query(
    "What is an Organizational Profile?"
)


print("\n" + "=" * 80)
print("QUESTION")
print("=" * 80)
print(result["question"])


print("\n" + "=" * 80)
print("ANSWER")
print("=" * 80)
print(result["answer"])


print("\n" + "=" * 80)
print("VALIDATED CITATIONS")
print("=" * 80)

for citation in result["citations"]:
    print(
        f"\nSource {citation['source_number']}"
        f" | Page: {citation['page']}"
        f" | Chunk: {citation['chunk_id']}"
        f" | Document: {citation['source']}"
    )


print("\n" + "=" * 80)
print("INVALID CITATIONS")
print("=" * 80)

print(result["invalid_citations"])


print("\n" + "=" * 80)
print("GROUNDING EVALUATION")
print("=" * 80)

for evaluation in result["grounding"]:

    print("\nCLAIM:")
    print(evaluation["claim"])

    print("\nSTATUS:")
    print(evaluation["status"])

    print("\nSOURCE EVALUATIONS:")

    for source in evaluation["sources"]:
        print(source)


print("\n" + "=" * 80)
print("RETRIEVED SOURCES")
print("=" * 80)

for rank, source in enumerate(
    result["sources"],
    start=1,
):
    print(
        f"\nRank {rank}"
        f" | Score: {source['score']:.4f}"
        f" | Page: {source['metadata']['page']}"
        f" | Chunk: {source['metadata']['chunk_id']}"
    )