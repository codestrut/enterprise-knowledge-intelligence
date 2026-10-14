"""Tests for recording and replaying grounding on frozen answers."""

import tempfile
from pathlib import Path

import pytest

from src.evaluation.grounding_replay import (
    CachedClaimDecomposer,
    ReplayCacheMiss,
    count_statuses,
    load_run,
    record_item,
    replay_run,
    save_run,
    status_flips,
    summarize,
)


class CountingInner:
    def __init__(self):
        self.calls = []

    def decompose(self, claim, context=None):
        self.calls.append((claim, context))
        return [f"{claim} (a)", f"{claim} (b)"]


def test_cache_miss_calls_inner_once_then_hits():
    inner = CountingInner()
    cached = CachedClaimDecomposer(inner=inner)
    first = cached.decompose("Claim one.")
    second = cached.decompose("Claim one.")
    assert first == second == ["Claim one. (a)", "Claim one. (b)"]
    assert len(inner.calls) == 1
    assert (cached.hits, cached.misses) == (1, 1)


def test_context_is_part_of_the_cache_key():
    inner = CountingInner()
    cached = CachedClaimDecomposer(inner=inner)
    cached.decompose("It covers roles.", context="The CSF defines GV.")
    cached.decompose("It covers roles.", context="Another subject.")
    assert len(inner.calls) == 2


def test_cache_persists_across_instances():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "cache.json"
        CachedClaimDecomposer(inner=CountingInner(), cache_path=path).decompose("X.")
        inner = CountingInner()
        reloaded = CachedClaimDecomposer(inner=inner, cache_path=path)
        assert reloaded.decompose("X.") == ["X. (a)", "X. (b)"]
        assert inner.calls == []


def test_offline_mode_raises_on_a_miss_and_never_calls_inner():
    inner = CountingInner()
    cached = CachedClaimDecomposer(inner=inner, offline=True)
    with pytest.raises(ReplayCacheMiss):
        cached.decompose("Unseen claim.")
    assert inner.calls == []


def test_summarize_counts_uncited_in_the_denominator():
    items = [
        {
            "answerable": True,
            "refused": False,
            "grounding": [{"status": "grounded"}, {"status": "uncited"}],
        },
        {
            "answerable": True,
            "refused": False,
            "grounding": [{"status": "grounded"}, {"status": "grounded"}],
        },
        {"answerable": False, "refused": True, "grounding": []},
    ]
    summary = summarize(items)
    assert summary["total_claims"] == 4
    assert summary["uncited_claims"] == 1
    assert summary["grounded_claim_rate"] == 0.75
    assert summary["answered_queries"] == 2
    assert summary["grounded_answers"] == 1
    assert summary["grounded_answer_rate"] == 0.5


def test_summarize_handles_no_claims():
    summary = summarize([{"answerable": False, "refused": True, "grounding": []}])
    assert summary["total_claims"] == 0
    assert summary["grounded_claim_rate"] == 0.0
    assert summary["grounded_answer_rate"] == 0.0


def test_count_statuses_ignores_unknown_values():
    assert count_statuses([{"status": "grounded"}, {"status": "weird"}])["grounded"] == 1


def test_record_roundtrip_restores_integer_source_map_keys():
    item = {"query": "What is X?", "answerable": True}
    result = {
        "refused": False,
        "answer": "X is Y. [Source 1]",
        "source_map": {1: {"source": "a.pdf", "page": 2, "chunk_id": 7}},
        "sources": [{"text": "X is Y.", "score": 0.5}],
        "evidence": {"sufficient": True},
        "grounding": [
            {
                "claim": "X is Y.",
                "status": "grounded",
                "atomic_claims": [{
                    "claim": "X is Y.",
                    "status": "grounded",
                    "sources": [{
                        "source_number": 1,
                        "label": "entailment",
                        "evidence": [{
                            "label": "neutral",
                            "raw_label": "neutral",
                            "relation_guard": {"applied": False, "reason": "raw neutral"},
                            "probabilities": {"contradiction": 0.01, "entailment": 0.98, "neutral": 0.01},
                            "evidence": "X is Y.",
                        }],
                    }],
                }],
            }
        ],
    }
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "run.json"
        save_run(path, [record_item(item, result)], {"note": "test"})
        loaded = load_run(path)
    record = loaded["records"][0]
    assert list(record["source_map"]) == [1]
    assert record["source_map"][1]["page"] == 2
    assert record["recorded_grounding"][0]["status"] == "grounded"
    evidence_diag = record["recorded_grounding"][0]["atomic_claims"][0]["sources"][0]["evidence"][0]
    assert evidence_diag["raw_label"] == "neutral"
    assert evidence_diag["relation_guard"]["reason"] == "raw neutral"
    assert loaded["metadata"]["note"] == "test"


def test_load_run_rejects_unknown_schema():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "run.json"
        path.write_text('{"schema_version": 99, "records": []}')
        with pytest.raises(ValueError):
            load_run(path)


def test_status_flips_reports_changed_new_and_removed_claims():
    recorded = [
        {"claim": "A", "status": "grounded"},
        {"claim": "B", "status": "unsupported"},
        {"claim": "C", "status": "grounded"},
    ]
    replayed = [
        {"claim": "A", "status": "grounded"},
        {"claim": "B", "status": "contradicted"},
        {"claim": "D", "status": "uncited"},
    ]
    flips = {f["claim"]: (f["before"], f["after"]) for f in status_flips(recorded, replayed)}
    assert flips == {
        "B": ("unsupported", "contradicted"),
        "C": ("grounded", "(not parsed)"),
        "D": ("(not parsed)", "uncited"),
    }


class StubEvaluator:
    def __init__(self):
        self.calls = []

    def evaluate(self, answer, source_map, source_documents):
        self.calls.append((answer, source_map, source_documents))
        return [{"claim": "X is Y.", "status": "uncited", "atomic_claims": []}]


def test_replay_skips_refused_records_and_reports_flips():
    records = [
        {
            "query": "q1",
            "answerable": True,
            "refused": False,
            "answer": "X is Y.",
            "source_map": {1: {}},
            "sources": [{"text": "X is Y."}],
            "recorded_grounding": [
                {"claim": "X is Y.", "status": "grounded", "atomic_claims": []}
            ],
        },
        {
            "query": "q2",
            "answerable": False,
            "refused": True,
            "answer": "refused",
            "source_map": {},
            "sources": [],
            "recorded_grounding": [],
        },
    ]
    evaluator = StubEvaluator()
    replayed = replay_run(records, evaluator)
    assert len(evaluator.calls) == 1
    assert replayed[1]["grounding"] == []
    assert replayed[0]["flips"] == [
        {"claim": "X is Y.", "before": "grounded", "after": "uncited"}
    ]
