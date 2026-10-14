# EKIP MVP Evaluation Baseline Freeze

## Purpose

Freeze the exact labelled query dataset, corpus fingerprint, key code fingerprints, Python version and selected dependency versions before another quality-changing patch. This is designed to be additive and read-only with respect to the RAG pipeline.

## Create the first manifest

Run from the EKIP project root:

```bash
python -m py_compile scripts/freeze_eval_manifest.py
python scripts/freeze_eval_manifest.py
```

The default output is:

`reports/evaluation/ekip-mvp-baseline-v1-manifest.json`

The helper refuses to overwrite an existing manifest unless `--force` is explicitly supplied. Preserve the first manifest as the baseline; create a differently named manifest for later changes if you intentionally re-freeze.

If the corpus uses another path:

```bash
python scripts/freeze_eval_manifest.py --document path/to/active-corpus.pdf --out reports/evaluation/ekip-mvp-baseline-v1-manifest.json
```

## What it captures

- Evaluation query text, answerable/unanswerable designation, labels and dataset SHA-256.
- Corpus SHA-256 and size, when the configured corpus path exists.
- Hashes of evaluation, pipeline, prompt, grounding and retrieval source files when present.
- Git commit, branch, dirty-tree state and changed paths; it does not commit, stash, reset or alter the user's work.
- Python/platform and versions of selected ML/RAG dependencies.

It does not store raw corpus text, generated answers, environment-variable values, API secrets or live replay output. It is a configuration fingerprint, **not yet a full deterministic replay bundle**. Exact replay is the next evaluation task: preserve query-by-query results, retrieved source IDs, prompt/config fingerprints and model/runtime settings.

## Minimum regression suite already established

The local test run on 2026-10-13 reported 26 passing tests for refusal/conflicting-source regressions plus grounding, repair and citation-related tests. Keep the focused command as part of the developer workflow, adjusting names only if the actual repository differs:

```bash
python -m pytest -q \
  tests/unit/test_refusal_conflict_regressions.py \
  tests/unit/test_grounding_evaluator.py \
  tests/unit/test_grounding_support_integration.py \
  tests/unit/test_answer_repair.py
```

## Known next gaps

1. Add requester identity and permitted source IDs to each case before claiming ACL-aware evaluation coverage.
2. Add a pair of explicitly conflicting sources with authority/effective-date metadata and expected behavior.
3. Keep the four currently labelled unanswerable questions, but test them as reusable regression cases and add at least one partial-evidence case.
4. Freeze source/retrieved-context replay separately from this manifest so generation changes can be measured without normal model-output variance.
5. Benchmark recall@k under selective ACL filters when ACL-aware retrieval is introduced; current retrieval metrics are not evidence of ACL-filtered recall.
