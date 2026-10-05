from src.generation.grounding_evaluator import GroundingEvaluator


class MockClaimDecomposer:
    """Mock claim decomposer for deterministic tests."""

    def __init__(self, decomposed_claims):
        self.decomposed_claims = decomposed_claims

    def decompose(self, claim):
        return self.decomposed_claims


class MockEvidenceSelector:
    """Mock evidence selector for deterministic tests."""

    def select(self, claim, evidence, top_k=2):
        if not claim or not evidence:
            return []

        return [
            {
                "text": evidence,
                "score": 0.9,
            }
        ]


class MockSemanticGrounder:
    """Mock semantic grounder for deterministic tests."""

    def __init__(self, label):
        self.label = label

    def check_claim(self, claim, evidence):
        return {
            "label": self.label,
            "probabilities": {
                "entailment": 0.99 if self.label == "entailment" else 0.01,
                "contradiction": 0.99 if self.label == "contradiction" else 0.01,
                "neutral": 0.99 if self.label == "neutral" else 0.01,
            },
        }


source_map = {
    1: {
        "source": "data/raw/nist_csf_2.0.pdf",
        "page": 11,
        "chunk_id": 38,
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
            "chunk_id": 38,
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


print("=" * 80)
print("TEST 1 — SUPPORTED ATOMIC CLAIM")
print("=" * 80)

answer = (
    "An Organizational Profile describes an organization's "
    "current cybersecurity posture. [Source 1]"
)

evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MockSemanticGrounder("entailment"),
    claim_decomposer=MockClaimDecomposer([
        (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture."
        )
    ]),
)

result = evaluator.evaluate(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)

print("\nRESULT:")
print(result)

assert result[0]["status"] == "grounded"
assert len(result[0]["atomic_claims"]) == 1
assert result[0]["atomic_claims"][0]["status"] == "grounded"


print("\n" + "=" * 80)
print("TEST 2 — CONTRADICTED ATOMIC CLAIM")
print("=" * 80)

answer = (
    "An Organizational Profile manages an organization's "
    "financial budget. [Source 1]"
)

evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MockSemanticGrounder("contradiction"),
    claim_decomposer=MockClaimDecomposer([
        (
            "An Organizational Profile manages an organization's "
            "financial budget."
        )
    ]),
)

result = evaluator.evaluate(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)

print("\nRESULT:")
print(result)

assert result[0]["status"] == "contradicted"
assert result[0]["atomic_claims"][0]["status"] == "contradicted"


print("\n" + "=" * 80)
print("TEST 3 — UNSUPPORTED ATOMIC CLAIM")
print("=" * 80)

answer = (
    "The organization operates offices in five countries. [Source 1]"
)

evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MockSemanticGrounder("neutral"),
    claim_decomposer=MockClaimDecomposer([
        "The organization operates offices in five countries."
    ]),
)

result = evaluator.evaluate(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)

print("\nRESULT:")
print(result)

assert result[0]["status"] == "unsupported"
assert result[0]["atomic_claims"][0]["status"] == "unsupported"


print("\n" + "=" * 80)
print("TEST 4 — COMPOUND CLAIM WITH ALL ATOMIC CLAIMS GROUNDED")
print("=" * 80)

answer = (
    "An Organizational Profile describes an organization's "
    "current and/or target cybersecurity posture, and is used "
    "to understand, tailor, assess, prioritize, and communicate "
    "the Core's outcomes. [Source 1]"
)

evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MockSemanticGrounder("entailment"),
    claim_decomposer=MockClaimDecomposer([
        (
            "An Organizational Profile describes an organization's "
            "current and/or target cybersecurity posture."
        ),
        (
            "An Organizational Profile is used to understand, "
            "tailor, assess, prioritize, and communicate the "
            "Core's outcomes."
        ),
    ]),
)

result = evaluator.evaluate(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)

print("\nRESULT:")
print(result)

assert result[0]["status"] == "grounded"
assert len(result[0]["atomic_claims"]) == 2

for atomic_claim in result[0]["atomic_claims"]:
    assert atomic_claim["status"] == "grounded"


print("\n" + "=" * 80)
print("TEST 5 — COMPOUND CLAIM WITH ONE UNSUPPORTED ATOMIC CLAIM")
print("=" * 80)

answer = (
    "An Organizational Profile describes an organization's "
    "current cybersecurity posture and is used to determine "
    "the organization's annual financial budget. [Source 1]"
)

evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MockSemanticGrounder("neutral"),
    claim_decomposer=MockClaimDecomposer([
        (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture."
        ),
        (
            "An Organizational Profile is used to determine "
            "the organization's annual financial budget."
        ),
    ]),
)

# First atomic claim should be grounded.
class MixedSemanticGrounder:
    """Return different grounding results for different claims."""

    def check_claim(self, claim, evidence):
        if "cybersecurity posture" in claim:
            return {
                "label": "entailment",
                "probabilities": {
                    "entailment": 0.99,
                    "contradiction": 0.005,
                    "neutral": 0.005,
                },
            }

        return {
            "label": "neutral",
            "probabilities": {
                "entailment": 0.005,
                "contradiction": 0.005,
                "neutral": 0.99,
            },
        }


evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MixedSemanticGrounder(),
    claim_decomposer=MockClaimDecomposer([
        (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture."
        ),
        (
            "An Organizational Profile is used to determine "
            "the organization's annual financial budget."
        ),
    ]),
)

result = evaluator.evaluate(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)

print("\nRESULT:")
print(result)

assert result[0]["atomic_claims"][0]["status"] == "grounded"
assert result[0]["atomic_claims"][1]["status"] == "unsupported"

# Critical conservative rule:
# one unsupported atomic claim means the overall compound claim
# must NOT be considered grounded.
assert result[0]["status"] == "unsupported"


print("\n" + "=" * 80)
print("TEST 6 — INVALID CITATION")
print("=" * 80)

answer = (
    "An Organizational Profile describes an organization's "
    "current cybersecurity posture. [Source 99]"
)

evaluator = GroundingEvaluator(
    evidence_selector=MockEvidenceSelector(),
    semantic_grounder=MockSemanticGrounder("entailment"),
    claim_decomposer=MockClaimDecomposer([
        (
            "An Organizational Profile describes an organization's "
            "current cybersecurity posture."
        )
    ]),
)

result = evaluator.evaluate(
    answer=answer,
    source_map=source_map,
    source_documents=source_documents,
)

print("\nRESULT:")
print(result)

assert result[0]["status"] == "unsupported"

assert (
    result[0]["atomic_claims"][0]["sources"][0]["label"]
    == "invalid"
)


print("\n" + "=" * 80)
print("ALL GROUNDING EVALUATOR TESTS PASSED")
print("=" * 80)