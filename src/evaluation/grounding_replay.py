"""Record generated answers once, then replay grounding on frozen inputs.

Generation and claim decomposition are stochastic LLM calls; evidence selection,
NLI and the guards are local. Live runs therefore mix two sources of change, so
a metric movement cannot be attributed to a code change. Freeze the answers
(and the decompositions) from one live run, then iterate on parsers, guards and
the NLI model against identical inputs.

This module is dependency-light: it imports no model libraries.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
STATUSES = ("grounded", "unsupported", "contradicted", "uncited")


class ReplayCacheMiss(KeyError):
    """Raised in offline mode when a claim has no cached decomposition."""


class CachedClaimDecomposer:
    """Wrap a decomposer with a persistent cache keyed by claim and context."""

    def __init__(self, inner=None, cache_path=None, offline=False):
        self.inner = inner
        self.cache_path = Path(cache_path) if cache_path else None
        self.offline = offline
        self.hits = 0
        self.misses = 0
        self._entries: dict[str, dict[str, Any]] = {}
        if self.cache_path and self.cache_path.exists():
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            self._entries = data.get("entries", {})

    @staticmethod
    def make_key(claim: str, context: str | None) -> str:
        payload = json.dumps([claim, context or ""], ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def decompose(self, claim, context=None):
        key = self.make_key(claim, context)
        if key in self._entries:
            self.hits += 1
            return list(self._entries[key]["atomic_claims"])

        if self.offline or self.inner is None:
            raise ReplayCacheMiss(
                f"No cached decomposition for claim: {claim[:80]!r}"
            )

        atomic = (
            self.inner.decompose(claim, context=context)
            if context
            else self.inner.decompose(claim)
        )
        self.misses += 1
        self._entries[key] = {
            "claim": claim,
            "context": context,
            "atomic_claims": list(atomic),
        }
        self.save()
        return list(atomic)

    def save(self):
        if not self.cache_path:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {"schema_version": SCHEMA_VERSION, "entries": self._entries},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def count_statuses(grounding: list[dict[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in STATUSES}
    for evaluation in grounding:
        status = evaluation.get("status")
        if status in counts:
            counts[status] += 1
    return counts


def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate claim and answer metrics.

    Every item needs ``answerable``, ``refused`` and ``grounding``. Uncited
    claims are part of the denominator, so a shrinking claim count cannot
    inflate the grounded rate.
    """
    totals = {status: 0 for status in STATUSES}
    for item in items:
        for status, count in count_statuses(item["grounding"]).items():
            totals[status] += count

    total_claims = sum(totals.values())
    answered = [item for item in items if not item["refused"]]
    grounded_answers = sum(
        1
        for item in answered
        if item["grounding"]
        and all(e.get("status") == "grounded" for e in item["grounding"])
    )

    def rate(count: int, denominator: int) -> float:
        return count / denominator if denominator else 0.0

    return {
        "queries": len(items),
        "answered_queries": len(answered),
        "total_claims": total_claims,
        "grounded_claims": totals["grounded"],
        "unsupported_claims": totals["unsupported"],
        "contradicted_claims": totals["contradicted"],
        "uncited_claims": totals["uncited"],
        "grounded_claim_rate": rate(totals["grounded"], total_claims),
        "unsupported_claim_rate": rate(totals["unsupported"], total_claims),
        "contradicted_claim_rate": rate(totals["contradicted"], total_claims),
        "uncited_claim_rate": rate(totals["uncited"], total_claims),
        "grounded_answers": grounded_answers,
        "grounded_answer_rate": rate(grounded_answers, len(answered)),
    }


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):  # numpy scalars
        return value.item()
    return str(value)


def _grounding_statuses(grounding: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Preserve full per-claim evidence and raw/effective guard diagnostics.

    The replay comparator reads only each top-level claim/status. Keeping the
    nested records here also preserves atomic statuses, selected evidence,
    raw NLI labels/probabilities, effective labels and guard reasons.
    """
    return json.loads(
        json.dumps(grounding, ensure_ascii=False, default=_json_default)
    )


def record_item(item: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Freeze one pipeline result so grounding can be replayed later."""
    return {
        "query": item["query"],
        "answerable": item["answerable"],
        "refused": bool(result["refused"]),
        "answer": result["answer"],
        "source_map": {str(k): v for k, v in result.get("source_map", {}).items()},
        "sources": result.get("sources", []),
        "evidence": result.get("evidence"),
        "recorded_grounding": _grounding_statuses(result.get("grounding", [])),
    }


def save_run(path, records: list[dict[str, Any]], metadata: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "metadata": metadata,
                "records": records,
            },
            indent=2,
            ensure_ascii=False,
            default=_json_default,
        ),
        encoding="utf-8",
    )


def load_run(path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported replay schema {data.get('schema_version')!r}; "
            f"expected {SCHEMA_VERSION}."
        )
    for record in data["records"]:
        record["source_map"] = {int(k): v for k, v in record["source_map"].items()}
    return data


def status_flips(
    recorded: list[dict[str, Any]], replayed: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """List claims whose status changed, appeared or disappeared."""
    before = {e["claim"]: e["status"] for e in recorded}
    after = {e["claim"]: e["status"] for e in replayed}
    flips = []
    for claim in dict.fromkeys([*before, *after]):
        old, new = before.get(claim, "(not parsed)"), after.get(claim, "(not parsed)")
        if old != new:
            flips.append({"claim": claim, "before": old, "after": new})
    return flips


def replay_run(records: list[dict[str, Any]], evaluator) -> list[dict[str, Any]]:
    """Re-run grounding on frozen answers and compare with the recorded run."""
    replayed = []
    for record in records:
        grounding = (
            []
            if record["refused"]
            else evaluator.evaluate(
                answer=record["answer"],
                source_map=record["source_map"],
                source_documents=record["sources"],
            )
        )
        replayed.append(
            {
                "query": record["query"],
                "answerable": record["answerable"],
                "refused": record["refused"],
                "grounding": grounding,
                "flips": status_flips(
                    record.get("recorded_grounding", []),
                    _grounding_statuses(grounding),
                ),
            }
        )
    return replayed
