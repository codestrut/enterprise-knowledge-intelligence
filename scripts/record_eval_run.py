"""Run the live pipeline once and freeze answers + claim decompositions.

    python scripts/record_eval_run.py --name 2026-10-12-baseline

Writes reports/replay/<name>.json and <name>.decompositions.json. These files
contain answers and retrieved source text; keep them out of version control if
the corpus is confidential.
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--document", default="data/raw/nist_csf_2.0.pdf")
    parser.add_argument("--backend", default=None, choices=["custom", "llamaindex"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out-dir", default="reports/replay")
    args = parser.parse_args()

    from src.evaluation.grounding_replay import (
        CachedClaimDecomposer,
        record_item,
        save_run,
        summarize,
    )
    from src.evaluation.retrieval_eval import EVALUATION_DATASET
    from src.rag_pipeline import RAGPipeline

    out_dir = Path(args.out_dir)
    run_path = out_dir / f"{args.name}.json"
    cache_path = out_dir / f"{args.name}.decompositions.json"

    pipeline = RAGPipeline(document_path=args.document, retrieval_backend=args.backend)
    evaluator = pipeline.grounding_evaluator
    evaluator.claim_decomposer = CachedClaimDecomposer(
        inner=evaluator.claim_decomposer, cache_path=cache_path
    )

    items = EVALUATION_DATASET[: args.limit] if args.limit else EVALUATION_DATASET
    records, summary_items = [], []
    for item in items:
        result = pipeline.query(item["query"])
        records.append(record_item(item, result))
        summary_items.append(
            {
                "answerable": item["answerable"],
                "refused": bool(result["refused"]),
                "grounding": result["grounding"],
            }
        )

    summary = summarize(summary_items)
    save_run(
        run_path,
        records,
        {
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "document": args.document,
            "retrieval_backend": pipeline.retrieval_backend,
            "llm_model": getattr(pipeline.llm, "model", None),
            "grounder_model": getattr(
                getattr(evaluator, "grounder", None), "model_name", None
            ),
            "summary": summary,
        },
    )
    print(f"Recorded {len(records)} queries to {run_path}")
    for key, value in summary.items():
        print(f"  {key}: {value:.4f}" if isinstance(value, float) else f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
