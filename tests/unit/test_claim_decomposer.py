from src.generation.claim_decomposer import ClaimDecomposer


class MockLLMClient:
    """Mock LLM client for deterministic decomposer tests."""

    def __init__(self, response):
        self.response = response

    def generate(self, prompt):
        return self.response


print("=" * 80)
print("TEST 1 — ATOMIC CLAIM")
print("=" * 80)

claim = (
    "An Organizational Profile describes an organization's "
    "current and/or target cybersecurity posture."
)

decomposer = ClaimDecomposer(
    llm_client=MockLLMClient(
        '["An Organizational Profile describes an organization\'s '
        'current and/or target cybersecurity posture."]'
    )
)

result = decomposer.decompose(claim)

print(result)

assert result == [
    "An Organizational Profile describes an organization's "
    "current and/or target cybersecurity posture."
]


print("\n" + "=" * 80)
print("TEST 2 — COMPOUND CLAIM")
print("=" * 80)

claim = (
    "An Organizational Profile describes an organization's "
    "current and/or target cybersecurity posture, and is used "
    "to understand, tailor, assess, prioritize, and communicate "
    "the Core's outcomes."
)

decomposer = ClaimDecomposer(
    llm_client=MockLLMClient(
        """[
            "An Organizational Profile describes an organization's current and/or target cybersecurity posture.",
            "An Organizational Profile is used to understand, tailor, assess, prioritize, and communicate the Core's outcomes."
        ]"""
    )
)

result = decomposer.decompose(claim)

print(result)

assert len(result) == 2
assert "current and/or target cybersecurity posture" in result[0]
assert "understand, tailor, assess, prioritize" in result[1]


print("\n" + "=" * 80)
print("TEST 3 — EMPTY CLAIM")
print("=" * 80)

decomposer = ClaimDecomposer(
    llm_client=MockLLMClient("[]")
)

result = decomposer.decompose("")

print(result)

assert result == []


print("\n" + "=" * 80)
print("TEST 4 — INVALID JSON")
print("=" * 80)

decomposer = ClaimDecomposer(
    llm_client=MockLLMClient(
        "This is not JSON."
    )
)

try:
    decomposer.decompose(
        "An organization manages cybersecurity risk."
    )
except ValueError as exc:
    print(f"ValueError correctly raised: {exc}")
else:
    raise AssertionError(
        "Expected ValueError for invalid JSON."
    )


print("\n" + "=" * 80)
print("ALL CLAIM DECOMPOSER TESTS PASSED")
print("=" * 80)