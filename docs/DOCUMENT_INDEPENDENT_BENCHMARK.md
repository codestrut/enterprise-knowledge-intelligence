# EKIP document-independent benchmark

## Purpose

EKIP's benchmark engine must be independent of the current NIST CSF 2.0 test corpus. The engine is JSON-driven and does not hard-code NIST terms, paths, file types, a vector-store implementation, or a universal retrieval-score threshold. Domain examples, corpora, document formats, questions, expected answerability, and labelled evidence/claim relationships belong in versioned suite files.

This starter provides two complementary evaluation layers:

1. **Cross-domain grounding smoke benchmark:** 18 labelled claim/evidence pairs covering HR, finance, IT operations, procurement, product manuals and records management. It checks entailment, contradiction, and neutral/insufficient evidence.
2. **Corpus-agnostic query benchmark:** a runner that invokes any provided pipeline adapter and reports answer/refusal, citation, claim-status, concept-coverage and per-case outcomes. It breaks reports down by domain, declared document format and calibration/held-out split.

This benchmark is intentionally diagnostic. A known model misclassification must be reported rather than hidden or relabelled to make the suite pass.

## Files

- `src/evaluation/document_independent_benchmark.py` — suite validation, corpus-agnostic query runner, label-aware grounding runner, metrics and JSON report writer.
- `data/evaluation/benchmarks/cross_domain_grounding.json` — 18 labelled cross-domain text pairs, with calibration and held-out smoke cases.
- `data/evaluation/benchmarks/query_benchmark_template.json` — starter template for query tests against one or more real corpus configurations.
- `tests/unit/test_document_independent_benchmark.py` — deterministic harness tests without model loading or external API calls.

## Apply and run harness tests

Copy the overlay's `src/`, `data/`, `tests/`, and `docs/` paths into the EKIP repository root without replacing existing files. Review all changes before commit.

```bash
python -m pytest -q tests/unit/test_document_independent_benchmark.py
```

The isolated overlay currently targets **15 deterministic tests**. Run the same command in the Mac project after copying the overlay; the local Mac checkout has not been modified by this archive.

## Run the live NLI diagnostic

```bash
python -m src.evaluation.document_independent_benchmark \
  --suite data/evaluation/benchmarks/cross_domain_grounding.json \
  --report reports/cross-domain-grounding-baseline.json
```

The command lazily loads the `SemanticGrounder` and writes a JSON report containing expected/predicted labels, all returned NLI probabilities, confusion matrix, accuracy, macro-F1, false-contradiction rate and metrics by domain, format label and split. It exits with status 1 when at least one labelled case is wrong, so the result cannot silently pass when the model is making mistakes.

Metrics include:

- **Accuracy and macro-F1:** overall and per group.
- **False-contradiction rate:** cases whose expected label is entailment or neutral but whose prediction is contradiction.
- **False-support rate:** cases whose expected label is contradiction or neutral but whose prediction is entailment.
- **Per-label precision, recall and F1:** so one class cannot hide failures in another.
- **Confusion matrix and per-case diagnostic:** expected label, predicted label, probabilities, evidence, claim, case ID and rationale.

## Add a real-corpus query suite

1. Copy `query_benchmark_template.json` to a versioned file named for the corpus/organization.
2. Define a `corpora` record for each document collection. Set a unique `id`, domain and actual document format; add adapter-specific settings such as document fixture path or knowledge-base identifier.
3. Add answerable and unanswerable query cases whose expected answerability has been reviewed by a person who checked the source documents.
4. Add `required_concept_groups` as curated aliases for the key concepts. This is a diagnostic lexical coverage measure—not a full semantic correctness gate.
5. Use `calibration` for development examples and `held_out` or `test` for cases not used to tune thresholds. Include independent held-out document collections, not only unseen questions over the same files.
6. Provide a `pipeline_factory(corpus_config)` returning an object with `query(question)`. Normalize the output to include `answer`, `refused`, `invalid_citations`, `grounding`, and `evidence` fields.
7. Run `run_query_benchmark(suite, pipeline_factory)` and persist its output with `write_report(report, "reports/<suite-id>.json")`.

The Python adapter is application-specific by design; the benchmark engine doesn't assume FastAPI, LangGraph, LangChain, FAISS, PostgreSQL, or any particular parser.


## Run a real corpus/query suite

Create a copy of `data/evaluation/benchmarks/query_benchmark_template.json`, replace all placeholders, and ensure each corpus entry has the settings required by its adapter. For the current single-document PDF path:

```bash
python -m src.evaluation.run_query_benchmark \
  --suite data/evaluation/benchmarks/your_suite.json \
  --factory examples.ekip_rag_pipeline_factory:build_pipeline \
  --report reports/your-suite-baseline.json
```

The adapter is an example for the current single-document constructor only. A corpus spread across multiple documents, one served by a tenant-scoped `KnowledgeBase`, or one requiring authenticated setup must use a custom `pipeline_factory(corpus_config)`. The benchmark runner caches one pipeline instance per corpus ID for the duration of the run.

Suites may declare an `acceptance_gates` object to enforce per-workload targets, for example:

```json
"acceptance_gates": {
  "minimum_answer_success_rate": 1.0,
  "minimum_refusal_accuracy": 1.0,
  "minimum_citation_validity_rate": 1.0
}
```

These are example, suite-specific targets—not global defaults. Supported gate keys are `minimum_answer_success_rate`, `minimum_refusal_accuracy`, `minimum_citation_validity_rate`, `minimum_grounded_claim_rate`, `minimum_fully_grounded_answer_rate_answerable`, `maximum_unsupported_claim_rate`, and `maximum_contradicted_claim_rate`. A configured gate with no applicable denominator fails as unknown; it is not silently treated as a pass. With no configured gates, the report is diagnostic only.

## Benchmark split and release rules

- Keep development/calibration data separate from held-out evaluation data. Do not tune a threshold on a case and cite that same case as evidence of generalization.
- The six held-out pairs in this starter are a smoke split, not statistically sufficient for a production generalization claim.
- The synthetic text-pair suite does not test actual extraction from PDF, DOCX, PPTX, XLSX/CSV, HTML/Markdown, scanned images/OCR, email, or structured exports. Add raw-file extraction fixtures and end-to-end suites for each advertised format.
- Add at least two independently selected corpus collections (e.g., HR policy and IT operations) and report metrics by domain and format.
- A non-zero `contradicted_claim_rate` from a generated-answer run is not enough to declare a false contradiction or an actual false claim. Inspect the exact claim/evidence and use the label-aware grounding set to measure false contradictions. Do not simply relax the old zero-rate assertion or tune a universal threshold to this NIST run.
- Calibrate score thresholds per retrieval/reranker model and relevant workload. Cross-encoder scores are not universal probabilities and may not be comparable across models.
- Preserve hard gates for citation provenance, refusal correctness, and authorization. Semantic judges supplement these guarantees; they don't replace them.
- Version the suite, report, model identity and configuration. Keep all failure details in JSON so diagnosis doesn't require rerunning the full benchmark.

## Current known project issues

The most recent user-provided end-to-end NIST run reports answer success 1.0000, refusal accuracy 1.0000 and citation validity 1.0000, but one of 11 claims is classified as contradicted (rate 0.0909), so the existing `contradicted_claim_rate == 0.0` assertion still fails. The exact claim/evidence must be inspected; it may be a model false positive or a genuinely conflicting generated claim. This overlay makes it possible to measure that distinction, but it does not itself fix the NLI model or prove the current pipeline passes.

The same run warns that an NLI tokenizer input reached 471 tokens against a 256-token limit. Safe segmentation/windowing must be implemented and tested separately to avoid truncation of decisive evidence.
