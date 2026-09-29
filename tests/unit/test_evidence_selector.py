"""Test evidence selection and failure handling."""

from src.generation.evidence_selector import EvidenceSelector


selector = EvidenceSelector(
    similarity_threshold=0.30,
)


evidence = """
An Organizational Profile describes an organization's current
and/or target cybersecurity posture in terms of the CSF Core outcomes.

Organizations can use Profiles to understand, tailor, assess,
prioritize, and communicate cybersecurity outcomes.

The CSF includes five Functions: Identify, Protect, Detect,
Respond, and Recover.
"""


print("\n" + "=" * 80)
print("TEST 1 — NORMAL CLAIM")
print("=" * 80)

results = selector.select(
    claim=(
        "An Organizational Profile describes an organization's "
        "current and target cybersecurity posture."
    ),
    evidence=evidence,
    top_k=2,
)

for result in results:
    print(result)


print("\n" + "=" * 80)
print("TEST 2 — EMPTY CLAIM")
print("=" * 80)

print(
    selector.select(
        claim="",
        evidence=evidence,
        top_k=2,
    )
)


print("\n" + "=" * 80)
print("TEST 3 — EMPTY EVIDENCE")
print("=" * 80)

print(
    selector.select(
        claim="What is an Organizational Profile?",
        evidence="",
        top_k=2,
    )
)


print("\n" + "=" * 80)
print("TEST 4 — INVALID TOP_K")
print("=" * 80)

try:

    selector.select(
        claim="What is an Organizational Profile?",
        evidence=evidence,
        top_k=0,
    )

except ValueError as error:

    print(
        f"ValueError correctly raised: {error}"
    )


print("\n" + "=" * 80)
print("TEST 5 — UNRELATED CLAIM")
print("=" * 80)

results = selector.select(
    claim=(
        "The organization operates a fleet "
        "of commercial aircraft."
    ),
    evidence=evidence,
    top_k=2,
)

print(results)