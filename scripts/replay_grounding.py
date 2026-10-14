"""Replay grounding on a frozen run; no retrieval and no answer generation.

    python scripts/replay_grounding.py reports/replay/<name>.json
    python scripts/replay_grounding.py reports/replay/<name>.json --offline

With --offline, a claim with no cached decomposition is an error, so the result
depends only on local code and models. Without it, cache misses (for example
new claims produced by a changed parser) call the LLM and are cached.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run")
    parser.add_argument("--cache", default=None)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--report", default=None)
    args = parser.parse_args()

    from src.evaluation.grounding_replay import (
        CachedClaimDecomposer,
        load_run,
        replay_run,
        summarize,
    )
    from src.embeddings.embedder import Embedder
    from src.generation.grounding_evaluator import GroundingEvaluator

    run_path = Path(args.run)
    cache_path = Path(args.cache) if args.cache else run_path.with_suffix(
        ".decompositions.json"
    )
    run = load_run(run_path)

    inner = None
    if not args.offline:
        from src.generation.claim_decomposer import ClaimDecomposer

        inner = ClaimDecomposer()

    decomposer = CachedClaimDecomposer(
        inner=inner, cache_path=cache_path, offline=args.offline
    )
    evaluator = GroundingEvaluator(
        embedder=Embedder(), claim_decomposer=decomposer
    )

    replayed = replay_run(run["records"], evaluator)
    summary = summarize(replayed)
    recorded_summary = run.get("metadata", {}).get("summary", {})

    print(f"Replayed {len(replayed)} queries from {run_path}")
    print(f"Decomposition cache: {decomposer.hits} hits, {decomposer.misses} misses")
    print(f"{'metric':28}{'recorded':>12}{'replayed':>12}")
    for key, value in summary.items():
        old = recorded_summary.get(key)
        fmt = lambda v: "-" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))
        print(f"{key:28}{fmt(old):>12}{fmt(value):>12}")

    flips = [(r["query"], f) for r in replayed for f in r["flips"]]
    print(f"\nClaims whose status differs from the recorded run: {len(flips)}")
    for query, flip in flips:
        print(f"- [{flip['before']} -> {flip['after']}] {flip['claim']}\n    query: {query}")

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {
                    "source_run": str(run_path),
                    "offline": args.offline,
                    "summary": summary,
                    "queries": [
                        {
                            "query": r["query"],
                            "answerable": r["answerable"],
                            "refused": r["refused"],
                            "claims": [
                                {
                                    "claim": e.get("claim"),
                                    "status": e.get("status"),
                                    "atomic_claims": e.get("atomic_claims", []),
                                    "reason": e.get("reason"),
                                }
                                for e in r["grounding"]
                            ],
                            "flips": r["flips"],
                        }
                        for r in replayed
                    ],
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nReport written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
