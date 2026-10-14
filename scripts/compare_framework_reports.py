#!/usr/bin/env python3
"""Compare two JSON reports produced by run_framework_eval.py."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

METRICS = (
    "answer_success_rate",
    "refusal_accuracy",
    "citation_validity_rate",
    "grounded_claim_rate",
    "unsupported_claim_rate",
    "contradicted_claim_rate",
    "grounded_answer_rate",
    "hit_at_5",
    "recall_at_5",
    "mrr",
    "ragas_faithfulness_mean",
    "mean_latency_seconds",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", help="Path to custom-backend JSON report")
    parser.add_argument("candidate", help="Path to LlamaIndex-backend JSON report")
    args = parser.parse_args()
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    candidate = json.loads(Path(args.candidate).read_text(encoding="utf-8"))
    baseline_queries = [row.get("query") for row in baseline.get("queries", [])]
    candidate_queries = [row.get("query") for row in candidate.get("queries", [])]
    if baseline_queries != candidate_queries:
        print("WARNING: reports do not contain the same ordered query set; deltas may not be comparable.")
    print(f"Baseline: {baseline.get('backend')} ({baseline.get('query_count')} queries)")
    print(f"Candidate: {candidate.get('backend')} ({candidate.get('query_count')} queries)")
    print(f"{'Metric':35} {'Baseline':>14} {'Candidate':>14} {'Delta':>14}")
    print("-" * 80)
    for metric in METRICS:
        left = baseline.get("metrics", {}).get(metric)
        right = candidate.get("metrics", {}).get(metric)
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            delta = right - left
            print(f"{metric:35} {left:14.4f} {right:14.4f} {delta:14.4f}")
        else:
            ltxt = "n/a" if left is None else str(left)
            rtxt = "n/a" if right is None else str(right)
            print(f"{metric:35} {ltxt:>14} {rtxt:>14} {'n/a':>14}")
    print("\nInterpretation rules:")
    print("- Treat small sample sizes as diagnostic, not conclusive.")
    print("- Do not accept a candidate that regresses refusal accuracy, citation validity, or contradiction gates.")
    print("- Do not compare runs unless query sets and corpus/chunking settings match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
