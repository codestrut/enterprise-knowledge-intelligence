# EKIP Framework Proof of Concept: LlamaIndex + Ragas

## Decision

This is an optional, reversible experiment. EKIP's custom RAG backend remains the default. The POC does not replace the existing FAISS, BM25, RRF, citation validator, evidence sufficiency gate, claim parser, or grounding gates.

- **LlamaIndex Core**: adapts EKIP's existing hybrid retriever to LlamaIndex nodes and supplies `SentenceTransformerRerank` as an alternative reranking implementation.
- **Ragas**: supplies an independent faithfulness score over the generated response and retrieved contexts. This score is reported separately from EKIP's deterministic gates; it is not ground truth.
- **Existing EKIP evaluation**: remains responsible for answer/refusal success, citation validity, claim-level supported/unsupported/contradicted statuses, and known regression cases.

Official references:
- LlamaIndex rerankers: https://developers.llamaindex.ai/python/framework/module_guides/models/rerankers/
- LlamaIndex node postprocessors: https://developers.llamaindex.ai/python/framework/module_guides/querying/node_postprocessors/node_postprocessors/
- Ragas Faithfulness: https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/

## Install in the active virtual environment

From the repository root:

```bash
python -m pip install -r requirements.framework-poc.txt
```

The standard `requirements.txt` remains unchanged. LlamaIndex is optional and framework code is imported only when its backend is selected. Ragas dependencies are deliberately split into `requirements.ragas-poc.txt`; install those only if you choose to run the optional LLM-as-a-judge step.

## Run the quick comparison

First run a short, four-query smoke pass with the current custom retriever:

```bash
python scripts/run_framework_eval.py \
  --backend custom --limit 4 \
  --report reports/framework-poc/custom-smoke.json
```

Then run the same queries through LlamaIndex's reranker:

```bash
python scripts/run_framework_eval.py \
  --backend llamaindex --limit 4 \
  --report reports/framework-poc/llamaindex-smoke.json
```

Compare them:

```bash
python scripts/compare_framework_reports.py \
  reports/framework-poc/custom-smoke.json \
  reports/framework-poc/llamaindex-smoke.json
```

If the adapter smoke passes, run all twelve queries for both backends (same corpus and same environment), saving each report under `reports/framework-poc/`.

## Add Ragas evaluation

Ragas is installed separately so a dependency issue in the optional evaluator cannot block the LlamaIndex retrieval experiment. Ragas 0.4.3 has an upstream import-path compatibility issue with newer `langchain-community` releases; this POC pins `langchain-community==0.4.1` in the isolated optional requirements file. Before running the judge, install it with `python -m pip install -r requirements.ragas-poc.txt` and check dependencies with `python -m pip check`. It makes additional evaluator-model calls and requires `OPENAI_API_KEY`; optional evaluator model override:

```bash
export RAGAS_EVALUATOR_MODEL=gpt-4o-mini
python scripts/run_framework_eval.py \
  --backend llamaindex --limit 4 --with-ragas \
  --report reports/framework-poc/llamaindex-ragas-smoke.json
```

The default smoke run omits Ragas judge calls to limit cost. Ragas scores can vary and must not replace the existing hard gates.

## What is measured

The JSON report records:
- answer success and refusal accuracy;
- citation validity;
- grounded, unsupported and contradicted claim rates;
- fully grounded answer rate;
- answer latency;
- retrieval hit@5, recall@5 and MRR where relevant chunk labels map to the loaded corpus;
- optional Ragas faithfulness, per answer and mean.

If a relevant chunk ID does not exist in the current corpus/chunk configuration, the report identifies it and excludes that query from aggregate retrieval metrics. Repair stale benchmark labels before making decisions from retrieval scores.

## POC boundaries and acceptance

This first pass changes the retriever backend only; EKIP keeps its existing answer prompts, citations and grounding checks. Do not enable this globally or remove the custom backend until a matched full-suite comparison shows:

1. no regression in answer success, refusal accuracy, citation validity, or known contradiction tests;
2. retrieval metrics improve or are at least comparable on valid human-labelled cases;
3. grounded-answer/claim rates are not materially worse;
4. latency and cost remain acceptable;
5. the report has no judge/setup errors silently counted as scores.

The initial NIST corpus is small and generation is non-deterministic. Use the four-query run only as a smoke test, then run all twelve queries and expand the benchmark before any production decision.
