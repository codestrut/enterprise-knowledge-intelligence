# API response fixtures

`query-grounded.json` and `query-refused.json` were captured from the real FastAPI backend through the Vite proxy on 2026-10-15 during the prior Task 03.1 verification. They are sanitized copies; response shape and nesting are retained, strings are capped at 400 characters, and absolute paths are replaced with basenames. Details and test document cleanup are in the Task 03.1 handoff report in that earlier delivery.

`documents-empty.json` is the exact response from `GET http://127.0.0.1:5173/api/documents` through Vite on 2026-10-15. The response was HTTP 200 with `count: 0` and `documents: []`; paired health reported zero documents and chunks. Its capture and safety constraints are recorded in `documents-empty.README.md`.

`query-empty-refusal.json` is the exact JSON body from a read-only `POST http://127.0.0.1:5173/api/query` on 2026-10-15 against that empty knowledge base. It returned HTTP 200 in 0.020526 seconds with `refused: true`, `evidence.sufficient: false`, and no sources or citations.

No one-document list, upload, duplicate, wrong-file, oversized-file, or delete fixture is labelled as real in this task. Those operations persist to or delete files in the protected repository `data/` directory, which Task 04 forbids modifying. Such code paths are covered using mocked API responses in frontend tests; live mutation workflow coverage is not verified.
