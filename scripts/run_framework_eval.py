#!/usr/bin/env python3
"""Run the same EKIP query dataset with the custom or LlamaIndex retriever.

Examples:
  python scripts/run_framework_eval.py --backend custom --limit 4 \
      --report reports/framework-poc/custom-smoke.json
  python scripts/run_framework_eval.py --backend llamaindex --limit 4 \
      --report reports/framework-poc/llamaindex-smoke.json
  python scripts/run_framework_eval.py --backend llamaindex --with-ragas \
      --report reports/framework-poc/llamaindex-full.json

The default fast path does not call an additional LLM judge. Add --with-ragas
for an independent faithfulness evaluation; this makes extra API calls and cost.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.retrieval_eval import (  # noqa: E402
    EVALUATION_DATASET,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
    resolve_relevant_evidence,
)
from src.rag_pipeline import RAGPipeline  # noqa: E402


def _chunk_ids(documents: list[dict[str, Any]]) -> list[Any]:
    ids: list[Any] = []
    for document in documents:
        value = (document.get("metadata") or {}).get("chunk_id")
        if value is not None:
            ids.append(value)
    return ids


def _guard_downgrade_details(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect raw NLI contradictions and guard interventions for manual review.

    Evidence text is intentionally included only when the caller opts in via
    --include-grounding-details because reports may contain confidential data.
    """
    records: list[dict[str, Any]] = []
    for claim_entry in result.get("grounding", []):
        for atomic in claim_entry.get("atomic_claims", []):
            for source in atomic.get("sources", []):
                for check in source.get("evidence", []):
                    relation_guard = check.get("relation_guard") or {}
                    raw_label = check.get("raw_label", check.get("label"))
                    if raw_label != "contradiction" and not relation_guard.get("applied"):
                        continue
                    records.append({
                        "claim": claim_entry.get("claim"),
                        "claim_status": claim_entry.get("status"),
                        "atomic_claim": atomic.get("claim"),
                        "atomic_claim_status": atomic.get("status"),
                        "source_number": source.get("source_number"),
                        "source_label": source.get("label"),
                        "raw_nli_label": raw_label,
                        "effective_nli_label": check.get("label"),
                        "probabilities": check.get("probabilities", {}),
                        "evidence_score": check.get("evidence_score"),
                        "relation_guard_applied": bool(relation_guard.get("applied")),
                        "relation_guard_reason": relation_guard.get("reason"),
                        "shared_content_terms": relation_guard.get("shared_content_terms", []),
                        "support_guard_applied": bool((check.get("support_guard") or {}).get("applied")),
                        "support_guard_reason": (check.get("support_guard") or {}).get("reason"),
                        # Deliberately verbose/sensitive fields; opt-in flag controls writing.
                        "evidence_text": check.get("evidence"),
                    })
    return records


def _claim_counts(result: dict[str, Any]) -> dict[str, int]:
    statuses = [item.get("status") for item in result.get("grounding", [])]
    return {
        "total_claims": len(statuses),
        "grounded_claims": sum(status == "grounded" for status in statuses),
        "unsupported_claims": sum(status == "unsupported" for status in statuses),
        "contradicted_claims": sum(status == "contradicted" for status in statuses),
        "uncited_claims": sum(status == "uncited" for status in statuses),
    }



def _raw_nli_diagnostics(result: dict[str, Any]) -> dict[str, int]:
    """Count raw NLI contradictions and guard downgrades separately from claim status."""
    raw_contradictions = 0
    downgraded_by_relation_guard = 0
    for claim in result.get("grounding", []):
        for atomic in claim.get("atomic_claims", []):
            for source in atomic.get("sources", []):
                for evidence in source.get("evidence", []):
                    if evidence.get("raw_label") != "contradiction":
                        continue
                    raw_contradictions += 1
                    guard = evidence.get("relation_guard", {})
                    if guard.get("applied") and evidence.get("label") != "contradiction":
                        downgraded_by_relation_guard += 1
    return {
        "raw_nli_contradictions": raw_contradictions,
        "relation_guard_downgrades": downgraded_by_relation_guard,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    pipeline = RAGPipeline(
        document_path=args.document,
        retrieval_backend=args.backend,
    )
    scorer = None
    if args.with_ragas:
        from src.evaluation.ragas_evaluator import build_faithfulness_scorer
        scorer = build_faithfulness_scorer()

    selected = EVALUATION_DATASET[: args.limit] if args.limit else EVALUATION_DATASET
    if not selected:
        raise ValueError("The selected evaluation dataset is empty.")

    total = {
        "answerable_count": 0,
        "answered_answerable": 0,
        "unanswerable_count": 0,
        "correct_refusals": 0,
        "citation_valid_count": 0,
        "answer_count": 0,
        "total_claims": 0,
        "grounded_claims": 0,
        "unsupported_claims": 0,
        "contradicted_claims": 0,
        "uncited_claims": 0,
        "raw_nli_contradictions": 0,
        "relation_guard_downgrades": 0,
        "fully_grounded_answers": 0,
    }
    query_results = []

    for index, item in enumerate(selected, start=1):
        started = time.perf_counter()
        response = pipeline.query(item["query"])
        elapsed = time.perf_counter() - started

        counts = _claim_counts(response)
        raw_nli = _raw_nli_diagnostics(response)
        answered = not bool(response.get("refused"))
        citation_valid = not bool(response.get("invalid_citations"))
        fully_grounded = counts["total_claims"] > 0 and counts["grounded_claims"] == counts["total_claims"]

        if item["answerable"]:
            total["answerable_count"] += 1
            total["answered_answerable"] += int(answered)
        else:
            total["unanswerable_count"] += 1
            total["correct_refusals"] += int(not answered)
        total["citation_valid_count"] += int(citation_valid)
        total["answer_count"] += int(answered)
        for key in (
            "total_claims", "grounded_claims", "unsupported_claims",
            "contradicted_claims", "uncited_claims",
        ):
            total[key] += counts[key]
        for key, value in raw_nli.items():
            total[key] += value
        total["fully_grounded_answers"] += int(answered and fully_grounded)

        sources = response.get("sources", [])
        retrieved_ids = _chunk_ids(sources)
        item_result: dict[str, Any] = {
            "id": index,
            "query": item["query"],
            "answerable": bool(item["answerable"]),
            "answered": answered,
            "refused": not answered,
            "latency_seconds": round(elapsed, 4),
            "citation_valid": citation_valid,
            "citation_count": len(response.get("citations", [])),
            **counts,
            **raw_nli,
            "fully_grounded": fully_grounded,
            "retrieved_chunk_ids": retrieved_ids,
            "retrieved_context_count": sum(
                bool(source.get("text", "").strip()) for source in sources
            ),
            "grounding_statuses": [entry.get("status") for entry in response.get("grounding", [])],
            # Lightweight control-flow diagnostics are safe to retain in the
            # evaluation report and help distinguish evidence-gate refusals
            # from model abstentions or failed recovery attempts.
            "evidence_gate": response.get("evidence"),
            "generation_repair": response.get("generation_repair"),
        }
        if args.include_grounding_details:
            # The selected entries contain claim/evidence text; use this only
            # in a local, access-controlled diagnostic report.
            item_result["grounding_diagnostics"] = _guard_downgrade_details(response)

        retrieved_contexts = [
            source.get("text", "") for source in sources if source.get("text", "").strip()
        ]
        if args.include_text:
            # Opt-in only: can contain customer-sensitive document content.
            item_result["answer"] = response.get("answer", "")
            item_result["retrieved_contexts"] = retrieved_contexts

        # Resolve source-text anchors against the current corpus. Sequential
        # chunk IDs drift when chunking changes, so labels must not rely on them.
        all_chunks = pipeline.chunks if getattr(pipeline, "chunks", None) else []
        evidence_anchors = item.get("relevant_evidence", [])
        gold_ids, unmapped_evidence = resolve_relevant_evidence(
            all_chunks, evidence_anchors
        )
        # Exclude a case from aggregate retrieval metrics unless every expected
        # evidence anchor maps. Partial mapping would shrink recall's denominator.
        scoreable = bool(gold_ids) and not unmapped_evidence
        if unmapped_evidence:
            print(
                f"[RETRIEVAL LABEL WARNING] {item['query']}: "
                f"{len(unmapped_evidence)} anchor(s) failed to map"
            )

        item_result["retrieval"] = {
            "gold_evidence_anchors": evidence_anchors,
            "mapped_relevant_chunk_ids": gold_ids,
            "unmapped_relevant_evidence": unmapped_evidence,
            "scoreable": scoreable,
            "hit_at_5": hit_at_k(retrieved_ids, gold_ids, 5) if scoreable else None,
            "recall_at_5": recall_at_k(retrieved_ids, gold_ids, 5) if scoreable else None,
            "mrr": reciprocal_rank(retrieved_ids, gold_ids) if scoreable else None,
            "note": (
                "Scored using source-text anchors resolved against the current chunking."
                if scoreable
                else "Excluded: one or more gold evidence anchors did not map to the current corpus."
            ),
        }

        if scorer is not None and answered:
            from src.evaluation.ragas_evaluator import score_faithfulness
            try:
                item_result["ragas_faithfulness"] = await score_faithfulness(
                    scorer,
                    query=item["query"],
                    answer=response.get("answer", ""),
                    contexts=retrieved_contexts,
                )
            except Exception as exc:  # preserve other results when judge call fails
                item_result["ragas_faithfulness_error"] = f"{type(exc).__name__}: {exc}"
        else:
            item_result["ragas_faithfulness"] = None

        query_results.append(item_result)
        print(
            f"[{index}/{len(selected)}] {item['query']} | "
            f"claims={counts['total_claims']} grounded={counts['grounded_claims']} "
            f"unsupported={counts['unsupported_claims']} contradicted={counts['contradicted_claims']} "
            f"uncited={counts['uncited_claims']} raw_nli_contradictions={raw_nli['raw_nli_contradictions']} "
            f"latency={elapsed:.2f}s"
        )

    total_claims = total["total_claims"]
    answer_count = total["answer_count"]
    relevant_retrieval_results = [
        entry["retrieval"] for entry in query_results
        if entry.get("retrieval", {}).get("mrr") is not None
    ]
    faithfulness_values = [
        entry["ragas_faithfulness"]["value"] for entry in query_results
        if isinstance(entry.get("ragas_faithfulness"), dict)
        and isinstance(entry["ragas_faithfulness"].get("value"), (int, float))
    ]
    metrics = {
        "answer_success_rate": total["answered_answerable"] / total["answerable_count"] if total["answerable_count"] else None,
        "refusal_accuracy": total["correct_refusals"] / total["unanswerable_count"] if total["unanswerable_count"] else None,
        "citation_validity_rate": total["citation_valid_count"] / len(query_results) if query_results else None,
        "grounded_claim_rate": total["grounded_claims"] / total_claims if total_claims else None,
        "unsupported_claim_rate": total["unsupported_claims"] / total_claims if total_claims else None,
        "contradicted_claim_rate": total["contradicted_claims"] / total_claims if total_claims else None,
        "uncited_claim_rate": total["uncited_claims"] / total_claims if total_claims else None,
        "uncited_claims": total["uncited_claims"],
        "raw_nli_contradictions": total["raw_nli_contradictions"],
        "relation_guard_downgrades": total["relation_guard_downgrades"],
        "grounded_answer_rate": total["fully_grounded_answers"] / answer_count if answer_count else None,
        "mean_latency_seconds": statistics.mean(entry["latency_seconds"] for entry in query_results),
        "retrieval_cases_scored": len(relevant_retrieval_results),
        "hit_at_5": statistics.mean(entry["hit_at_5"] for entry in relevant_retrieval_results) if relevant_retrieval_results else None,
        "recall_at_5": statistics.mean(entry["recall_at_5"] for entry in relevant_retrieval_results) if relevant_retrieval_results else None,
        "mrr": statistics.mean(entry["mrr"] for entry in relevant_retrieval_results) if relevant_retrieval_results else None,
        "ragas_faithfulness_mean": statistics.mean(faithfulness_values) if faithfulness_values else None,
        "ragas_faithfulness_scored_answers": len(faithfulness_values),
        "ragas_judge_errors": sum("ragas_faithfulness_error" in entry for entry in query_results),
    }
    report = {
        "schema_version": 1,
        "experiment": "ekip-llamaindex-ragas-poc-v1",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "document": args.document,
        "query_count": len(query_results),
        "with_ragas": bool(args.with_ragas),
        "ragas_evaluator_model": __import__("os").getenv("RAGAS_EVALUATOR_MODEL", "gpt-4o-mini") if args.with_ragas else None,
        "metrics": metrics,
        "queries": query_results,
        "notes": [
            "Existing EKIP citation, refusal, and grounding gates remain the hard safety checks.",
            "Ragas faithfulness is an independent judge score and must not be treated as ground truth by itself.",
            "Raw answers and retrieved context are omitted unless --include-text is explicitly supplied.",
            "Retrieval metrics exclude cases whose labelled relevant chunk IDs do not map to the current corpus.",
            "LlamaIndex reranker scores are not directly comparable to EKIP RRF scores; compare ranking metrics instead.",
        ],
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nFramework POC summary")
    print(json.dumps(metrics, indent=2))
    print(f"Report: {report_path}")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("custom", "llamaindex"), required=True)
    parser.add_argument("--document", default="data/raw/nist_csf_2.0.pdf")
    parser.add_argument("--limit", type=int, default=None, help="Optional first-N query smoke test; omit to run all 12 queries.")
    parser.add_argument("--with-ragas", action="store_true", help="Run additional Ragas faithfulness judge calls.")
    parser.add_argument("--include-text", action="store_true", help="Include raw answers and retrieved context text in the JSON report (may contain sensitive data).")
    parser.add_argument(
        "--include-grounding-details",
        action="store_true",
        help="Include raw NLI contradiction/guard-downgrade claim-evidence pairs; report may contain sensitive data.",
    )
    parser.add_argument("--report", default=None, help="Output JSON report path.")
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be greater than zero.")
    if args.report is None:
        args.report = f"reports/framework-poc/{args.backend}.json"
    return args


if __name__ == "__main__":
    options = parse_args()
    asyncio.run(run(options))
