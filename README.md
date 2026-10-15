# Enterprise Knowledge Intelligence (EKIP)

Retrieval-augmented question answering with evidence-gated refusal, citation
validation and claim-level grounding. The current test corpus is the NIST
CSF 2.0 PDF.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "OPENAI_API_KEY=..." > .env          # never commit this file
mkdir -p data/raw                          # place nist_csf_2.0.pdf here (git-ignored)
```

## Tests

```bash
python -m pytest -q tests/unit                      # fast, no live LLM calls
python -m pytest -s tests/evaluation/test_rag_eval.py   # live end-to-end run
python -m scripts.check_chunk_lengths data/raw/nist_csf_2.0.pdf
```

## Grounding evaluation workflow

Live runs are stochastic (generation and claim decomposition are LLM calls).
Freeze one run, then change code against identical inputs:

```bash
python scripts/record_eval_run.py --name <run-name>
python scripts/replay_grounding.py reports/replay/<run-name>.json --offline
```

Claim statuses are `grounded`, `unsupported`, `contradicted` and `uncited`.
See `docs/GROUNDING_FIXES_2026-10-12.md` for the current behavior and
limitations.

## Frontend

The React + TypeScript development app lives in `frontend/`. Install its
dependencies and start Vite from that directory:

Prerequisites: Node.js `^22.22.2 || ^24.15.0 || >=26.0.0`, matching the
combined requirements of the frontend dependencies. Use a current npm
release compatible with your Node.js installation; the frontend does not
restrict the npm version.

```bash
cd frontend
npm ci
npm run dev
```

The app expects the FastAPI backend at `http://127.0.0.1:8000` by default.
Set `EKIP_API_PROXY_TARGET` in the environment before starting Vite to use a
different backend URL, for example:

```bash
EKIP_API_PROXY_TARGET=http://localhost:8001 npm run dev
```

The frontend calls `/api/health` and `/api/query`; Vite rewrites `/api` and
proxies those paths to the backend's `/health` and `/query` routes. The
`/api/documents` prefix is also available for future frontend API requests.
Type-check, test and build the frontend with `npm run check`,
`npm test -- --reporter=dot`, and `npm run build` from `frontend/`.
