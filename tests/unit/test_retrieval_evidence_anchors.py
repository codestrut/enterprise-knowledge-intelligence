"""Fast tests for stable text-anchored retrieval benchmark labels."""

from src.evaluation.retrieval_eval import (
    EVALUATION_DATASET,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
    resolve_relevant_evidence,
)


def _chunk(chunk_id, text):
    return {"text": text, "metadata": {"chunk_id": chunk_id, "page": 1}}


def test_anchor_resolution_ignores_chunk_id_drift_and_pdf_whitespace():
    chunks = [
        _chunk(36, "A CSF Organizational Profile describes an organization’s\ncurrent and/or target cybersecurity posture in terms of the Core’s outcomes."),
        _chunk(110, "Unrelated supply chain content."),
    ]
    anchor = "A CSF Organizational Profile describes an organization's current and/or target cybersecurity posture in terms of the Core's outcomes"

    resolved, unmapped = resolve_relevant_evidence(chunks, [anchor])

    assert resolved == [36]
    assert unmapped == []


def test_unmapped_anchor_is_reported_instead_of_silently_dropped():
    chunks = [_chunk(24, "Prioritize: Identify, organize, and prioritize cybersecurity actions.")]

    resolved, unmapped = resolve_relevant_evidence(
        chunks, ["a source phrase that is missing"]
    )

    assert resolved == []
    assert unmapped == ["a source phrase that is missing"]


def test_overlapping_chunks_do_not_duplicate_the_same_gold_anchor():
    phrase = "Cybersecurity roles and responsibilities are established and communicated"
    chunks = [
        _chunk(73, f"Roles, Responsibilities and Authorities. {phrase}. More unrelated text."),
        _chunk(74, f"Repeated overlap. {phrase}."),
    ]

    resolved, unmapped = resolve_relevant_evidence(chunks, [phrase])

    assert len(resolved) == 1
    assert unmapped == []


def test_retrieval_dataset_uses_text_anchors_not_numeric_chunk_ids():
    answerable_items = [item for item in EVALUATION_DATASET if item["answerable"]]

    assert len(answerable_items) == 8
    assert all(item.get("relevant_evidence") for item in answerable_items)
    assert all("relevant_chunks" not in item for item in answerable_items)


def test_anchor_based_retrieval_metrics_work_with_runtime_ids():
    chunks = [
        _chunk(24, "Prioritize: Identify, organize, and prioritize actions for managing cybersecurity risks."),
        _chunk(49, "Risk communication and integration."),
    ]
    anchor = "Prioritize: Identify, organize, and prioritize actions for managing cybersecurity risks"

    gold_ids, unmapped = resolve_relevant_evidence(chunks, [anchor])
    retrieved_ids = [49, 24]

    assert unmapped == []
    assert hit_at_k(retrieved_ids, gold_ids, 5) == 1
    assert recall_at_k(retrieved_ids, gold_ids, 5) == 1.0
    assert reciprocal_rank(retrieved_ids, gold_ids) == 0.5
