# Live query response fixtures

These JSON files are captured responses from the real FastAPI backend through the Vite development proxy at `http://127.0.0.1:5173/api/query` on 2026-10-15. The grounded-request fixture was captured with the existing NIST CSF 2.0 PDF temporarily indexed; the refusal fixture is the response to the unsupported Bitcoin-price question while the document was indexed. The grounded request returned HTTP 200 in 10.832 seconds with `refused: false`, a grounded claim and one citation. The unsupported request returned HTTP 200 in 0.489 seconds with `refused: true` and insufficient evidence.

The backend initially reported zero documents. The NIST PDF was uploaded through `/api/documents` only for these checks. After capture, only the returned temporary document ID was deleted. Both `/documents` and `/health` then reported zero documents and zero chunks. Upload and query outcomes, timings, and cleanup verification are recorded in `HANDOFF_REPORT.md`.

Sanitisation preserved the response keys, object structure, arrays, and nesting. Individual string values longer than 400 characters were truncated to 400 characters. Absolute filesystem path values were replaced with their basenames. No PDF, manifest, local evaluation data, credentials, or API keys are included.
