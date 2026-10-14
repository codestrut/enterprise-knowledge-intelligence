# Applying the EKIP framework POC overlay

This patch is a source overlay, not a replacement project snapshot. It only adds the optional framework adapter/evaluation files and a small backwards-compatible backend selector; it does not overwrite user data, `.env`, the NIST PDF, or unrelated files.

## Before applying

From the actual EKIP repository:

```bash
git branch --show-current
git status --short
git apply --check ~/Downloads/ekip-framework-poc.patch
```

Expected branch: `experiment/v6-grounding-and-claim-parser`.

The patch adds optional framework code and makes a small backwards-compatible change to `src/rag_pipeline.py`. The default retriever remains `custom`, so existing behavior is unchanged unless you opt in. If `git apply --check` fails, stop and share the error; do not reset or stash the existing working tree just to force the patch.

Apply only if the check passes:

```bash
git apply ~/Downloads/ekip-framework-poc.patch
```

## Install framework packages

Keep the existing `.venv` active:

```bash
python -m pip install -r requirements.framework-poc.txt
```

This file adds only the optional LlamaIndex dependency; it does not edit or replace the base `requirements.txt`. Ragas lives in a separate optional requirements file.

## Opt in

One-off Python construction:

```python
pipeline = RAGPipeline(
    document_path="data/raw/nist_csf_2.0.pdf",
    retrieval_backend="llamaindex",
)
```

Or opt in via environment variable for the existing launch command:

```bash
export EKIP_RETRIEVAL_BACKEND=llamaindex
```

Unset the variable or set it to `custom` to return to the existing backend. The default is `custom`.

## First comparison

Run four questions first for each backend, without Ragas judge calls:

```bash
python scripts/run_framework_eval.py --backend custom --limit 4 \
  --report reports/framework-poc/custom-smoke.json
python scripts/run_framework_eval.py --backend llamaindex --limit 4 \
  --report reports/framework-poc/llamaindex-smoke.json
python scripts/compare_framework_reports.py \
  reports/framework-poc/custom-smoke.json \
  reports/framework-poc/llamaindex-smoke.json
```

If the adapter runs successfully, repeat both runs without `--limit` so the full 12-query benchmark is used. The same corpus and query dataset are required for comparison.

For a separate independent faithfulness score, install Ragas **only after** the LlamaIndex smoke comparison works. Ragas 0.4.3 has a reported upstream import-path problem with newer `langchain-community` versions; the optional file pins `langchain-community==0.4.1`. See https://github.com/vibrantlabsai/ragas/issues/2745. Then check dependency resolution before running the judge:

```bash
python -m pip install -r requirements.ragas-poc.txt
python -m pip check
python scripts/run_framework_eval.py --backend llamaindex --limit 4 --with-ragas \
  --report reports/framework-poc/llamaindex-ragas-smoke.json
```

Ragas requires `OPENAI_API_KEY`; override the evaluator model with `RAGAS_EVALUATOR_MODEL` if needed. If installing Ragas conflicts with the app, skip it and keep running the LlamaIndex comparison. Ragas is diagnostic only: EKIP's own refusal, citation and grounding gates remain authoritative release checks.

## Not included in this POC

- No FAISS migration, re-chunking, embedding-model change or tenant/data-model change.
- No automatic use of LlamaIndex's synthesis or citation format; EKIP's existing prompt, source map, citation validator, evidence gate and claim evaluator remain in place.
- No fine-tuning or change to NLI thresholds.
- No permanent adoption decision. Compare quality, latency and cost first.
