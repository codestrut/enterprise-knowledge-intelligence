"""Deterministic tests for claim decomposition prompt and response handling."""

import pytest

from src.generation.claim_decomposer import ClaimDecomposer


class MockLLMClient:
    def __init__(self, response):
        self.response = response
        self.prompt = None

    def generate(self, prompt):
        self.prompt = prompt
        return self.response


def test_atomic_claim_is_returned_unchanged():
    claim = "An Organizational Profile describes an organization's posture."
    llm = MockLLMClient(
        '["An Organizational Profile describes an organization\'s posture."]'
    )
    assert ClaimDecomposer(llm_client=llm).decompose(claim) == [claim]


def test_compound_claim_can_be_decomposed_without_malformed_fragments():
    claim = (
        "C-SCRM emphasizes establishing a program, strategy, objectives, "
        "policies, and processes, and coordinating across suppliers."
    )
    expected = [
        "C-SCRM emphasizes establishing a program, strategy, objectives, policies, and processes.",
        "C-SCRM emphasizes coordinating across suppliers.",
    ]
    llm = MockLLMClient(__import__("json").dumps(expected))
    result = ClaimDecomposer(llm_client=llm).decompose(claim)
    assert result == expected
    assert "Do not split a coordinated list of nouns" in llm.prompt
    assert "grammatical, independently verifiable proposition" in llm.prompt


def test_context_is_included_for_pronoun_resolution_only():
    claim = "It helps align cybersecurity risk with enterprise risk management."
    context = (
        "Using the NIST CSF can support integration with the enterprise risk portfolio."
    )
    llm = MockLLMClient(
        '["The NIST CSF helps align cybersecurity risk with enterprise risk management."]'
    )
    result = ClaimDecomposer(llm_client=llm).decompose(claim, context=context)
    assert result == [
        "The NIST CSF helps align cybersecurity risk with enterprise risk management."
    ]
    assert "PRIOR ANSWER CONTEXT" in llm.prompt
    assert context in llm.prompt


def test_empty_claim_returns_empty_without_calling_llm():
    llm = MockLLMClient("[]")
    assert ClaimDecomposer(llm_client=llm).decompose(" ") == []
    assert llm.prompt is None


def test_invalid_json_raises_value_error():
    decomposer = ClaimDecomposer(llm_client=MockLLMClient("not json"))
    with pytest.raises(ValueError, match="invalid JSON"):
        decomposer.decompose("A cybersecurity fact.")


def test_prompt_preserves_established_referent_across_pronoun_chain():
    claim = "It also covers cybersecurity roles for suppliers and partners."
    context = (
        "NIST CSF 2.0 defines GV.RR. "
        "It states that organizational leadership is accountable."
    )
    llm = MockLLMClient(
        '["The NIST CSF 2.0 also covers cybersecurity roles for suppliers and partners."]'
    )
    result = ClaimDecomposer(llm_client=llm).decompose(claim, context=context)
    assert result == [
        "The NIST CSF 2.0 also covers cybersecurity roles for suppliers and partners."
    ]
    assert "Follow an already-established referent chain" in llm.prompt
    assert "NIST CSF 2.0 defines GV.RR" in llm.prompt


def test_prompt_requires_subject_and_agent_preservation():
    claim = (
        "The CSF helps executives translate cybersecurity risk into general risk language."
    )
    llm = MockLLMClient(
        '["The CSF helps executives translate cybersecurity risk into general risk language."]'
    )
    result = ClaimDecomposer(llm_client=llm).decompose(claim)
    assert result == [claim]
    assert "Preserve who or what performs each action" in llm.prompt
    assert "Never substitute a related entity as the grammatical subject or agent" in llm.prompt
