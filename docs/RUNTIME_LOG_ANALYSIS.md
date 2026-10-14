# EKIP runtime log analysis (2026-10-11)

## What the shared Uvicorn log establishes

1. `No active retriever; retrieval skipped.` occurred for query requests before the first successful `POST /documents` in the captured sequence. That is consistent with querying an empty in-memory knowledge base at that moment; it does not establish a post-upload failure. Later query requests in the log run embedding batches and do not emit the same warning.
2. `StatReload detected changes in ... tests/...` shows that Uvicorn's reloader is watching the whole repository, so changing unit tests causes the API process to restart and reload transformer models. Use `scripts/run_dev_api.sh` (which restricts reload to `src`) or run without `--reload` during long benchmarks. Stop the API before editing/running tests to avoid resource contention.
3. `Token indices sequence length is longer than ... (738 > 256)` is a real warning. The provided `text_chunker.py` long-paragraph path derives source character offsets from decoded token prefixes, then uses those lengths to slice the original string. Tokenizer normalization means decoded lengths are not guaranteed to match source offsets. That can produce chunks longer than the intended token limit and leads to model truncation or position-length errors.
4. `resource_tracker` reports leaked semaphore objects after repeated reloads/interrupts. The log alone doesn't prove a persistent runtime leak in steady-state use; model/process reload churn can expose cleanup warnings. Reduce reloads first and re-evaluate if this persists in a clean run.

## Patch included in this overlay

- `src/chunking/token_safe_splitter.py` uses tokenizer offset mappings to slice original text when available, with a token-ID bounded fallback for slow tokenizers.
- `apply_chunker_fix.py` preflights an exact source anchor, backs up `src/chunking/text_chunker.py`, and updates the oversized-paragraph branch. It aborts without edits if the local file diverges.
- `tests/unit/test_token_safe_splitter.py` checks bounded chunk lengths, overlap, source preservation and fallback behaviour.
- `scripts/check_chunk_lengths.py` validates the actual corpus's generated chunk tokens against the embedding model limit, including special tokens.
- `scripts/run_dev_api.sh` scopes Uvicorn's reload watcher to `src`, preventing changes to tests/docs/benchmark reports from triggering application/model reloads.

## Acceptance checks

1. Install the additive files with `apply_overlay.py`.
2. Run `apply_chunker_fix.py --dry-run`; only apply if it says `WOULD PATCH` or `ALREADY PATCHED`.
3. Run the splitter/chunker unit tests.
4. Validate the actual PDF with `python -m scripts.check_chunk_lengths data/raw/nist_csf_2.0.pdf`; every chunk must fit the embedding model maximum, including special tokens.
5. Start the API using `./scripts/run_dev_api.sh` only for development; stop it before test runs.
6. Re-run the cross-domain grounding suite; evaluate model predictions and guard decisions. Don't claim the 738-token issue is fixed merely because the unit tests pass.
