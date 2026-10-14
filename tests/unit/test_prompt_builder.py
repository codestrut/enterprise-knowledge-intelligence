"""Tests for grounding-critical answer prompt instructions."""

from src.generation.prompt_builder import SYSTEM_PROMPT, build_prompt


def test_prompt_requires_context_supported_enumerations():
    assert "include only entries explicitly supported by the supplied context" in SYSTEM_PROMPT
    assert "Do not fill missing entries from model memory" in SYSTEM_PROMPT


def test_prompt_rejects_standalone_list_introductions_as_facts():
    prompt = build_prompt("What are the risk tiers?", "Tier 1 is Partial.")
    assert '"Specific points include:"' in prompt
    assert "make each bullet a complete factual statement" in prompt


def test_prompt_preserves_source_scope_and_modality():
    assert "Preserve the source's scope and modality exactly" in SYSTEM_PROMPT
    assert '"one or both"' in SYSTEM_PROMPT
    assert "Do not describe a CSF outcome as a mandatory requirement" in SYSTEM_PROMPT


def test_prompt_preserves_actor_and_requires_support_for_each_clause():
    assert "Preserve the source's actor and agent" in SYSTEM_PROMPT
    assert "Every material clause in a sentence or bullet must be supported" in SYSTEM_PROMPT
    assert "do not use a related citation to imply support" in SYSTEM_PROMPT
