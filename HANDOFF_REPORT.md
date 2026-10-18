# EKIP Task 04 — Organisation Knowledge Management and Frontend Foundations

## Backend contract notes

Inspected directly in `src/api/main.py`, `src/api/document_records.py`, `src/api/document_fingerprints.py`, `src/api/rwlock.py`, and `src/knowledge_base.py` at baseline `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`.

1. **Upload — `POST /documents`**: multipart/form-data with required field `file` (`UploadFile`). Success is HTTP 201: `{ "message": string, "document": { document_id, filename, page_count, chunk_count, status, sha256 } }`. Public records filter out `source` and `stored_filename`. FastAPI returns HTTP 422 with a validation `detail` array if the required field is absent.
2. **List — `GET /documents`**: HTTP 200 `{ "count": number, "documents": DocumentRecord[] }`. Public active records expose fields such as `document_id`, `filename`, `page_count`, `chunk_count`, `status`, and `sha256`; metadata is treated as optional by the frontend.
3. **Delete — `DELETE /documents/{document_id}`**: HTTP 200 `{ message, document_id, filename, chunks_removed, file_deleted, cleanup_required }`. Unknown/malformed IDs return HTTP 404 `{ "detail": "Document not found: …" }`. Persistence/index errors return HTTP 500 with string `detail`.
4. **Health — `GET /health`**: HTTP 200 `{ status, document_count, chunk_count, manifest_exists, failed_document_count }`; `failed_document_count` may be `null` if manifest reading fails. Health uses in-memory indexed document/chunk counts and a manifest-derived failed count.
5. **Upload checks and limit**: filename extension must end in `.pdf` (case-insensitive), otherwise HTTP 400 `{detail: "Only PDF files are supported."}`. The body is streamed and limited to 25 MiB; excess is HTTP 413 `{detail: "PDF exceeds the 25 MB upload limit."}`. The first five bytes must equal `%PDF-`, otherwise HTTP 400 `{detail: "Uploaded file is not a valid PDF."}`. PDF parsing/embedding/indexing `ValueError` or `FileNotFoundError` becomes HTTP 400 string detail; other indexing/persistence errors become HTTP 500 `{detail: "Document upload or indexing failed."}`. Identical indexed content returns HTTP 409 with object detail `{message: "Identical PDF content is already indexed.", existing_document: public_record}`. Missing multipart field validation is HTTP 422 with FastAPI's `detail` array.
6. **Failed records**: `GET /documents` only returns `knowledge_base.list_documents()` records. Startup-failed manifest entries remain in the manifest and health's `failed_document_count`, but are omitted from the list. The frontend cannot offer row-level deletion for these records without a backend contract change.
7. **Synchronous work and locks**: Upload is a synchronous FastAPI handler. It streams, checks signature/size, and fingerprints before acquiring the exclusive read/write lock. Under that lock it checks duplicates, parses/chunks/embeds/indexes, and updates the manifest. The write lock blocks query and list read-lock requests, and serializes deletes. Health is intentionally lock-free and does not wait for indexing; its in-memory counts update when indexing updates the knowledge base. Client timeout/abort does not cancel server processing.
8. **Paths**: Internal knowledge-base records can contain `source` absolute paths. Manifest records contain `stored_filename`. `public_record()` filters both from upload/list responses. Frontend error text and rendered filenames are also path-sanitized; raw server paths are never intentionally rendered.
9. **Delete cleanup**: After removing the active record/chunks and manifest entry, deletion tries to unlink the stored PDF. `file_deleted: true` when unlink succeeds (including an already-absent file because `missing_ok=True`); on `OSError`, `cleanup_required: true` and `file_deleted: false`. Logical deletion can therefore succeed while file cleanup remains.
10. **Contract gaps**: There is no asynchronous job/status endpoint, server-side cancellation, progress percentage, per-document processing state, upload timestamp, or failed-document list endpoint. The UI uses indeterminate elapsed time, explains the server may continue after client abort, and refreshes the list for a later check. It does not fabricate progress or failed rows.

## Objective and implementation summary

Task 04 adds an organisation knowledge-management frontend over the existing API while preserving the RAG/query response contract. A shared `AppShell` and icon set now serve the dashboard, `/library`, and `/workspace`; a lightweight history-aware client router supports back/forward, titles, heading focus, and a 404 page. One shared status provider fetches health and documents on mount, deduplicates React Strict Mode effect replay, shares results between pages, and refreshes after library mutations without polling.

The dashboard now presents compact API-connectivity and knowledge-base signals, actual counts, supported failed-record count only when numeric, a zero-document upload action, and an evidence-based checklist. Question and citation-review checklist items remain incomplete because the app does not persist reliable evidence that those actions occurred.

The document library uses the existing synchronous multipart upload/list/delete API. It checks `.pdf`, the actual first-five-byte PDF signature, and the backend's 25 MiB limit; displays filename/size; shows elapsed indexing time without a percentage; supports Stop waiting with clear server-continuation guidance; and uses a native confirmation dialog for deletion. Duplicate object detail, 404, cleanup state, validation, gateway, network, and timeout responses have actionable UI paths. Desktop tables switch to narrow-screen cards. Names and API errors are sanitized against server paths.

The workspace keeps its query, grounding, citation, refusal, diagnostics, and cancellation logic. It now reads shared document scope, shows a zero-document upload card, and provides generic question examples that fill and focus the textarea without submitting. The backend remains responsible for evidence-gated refusal.

## Files changed and why

Tracked files changed:

- `README.md` — documents the three UI routes and existing document API proxy operations.
- `frontend/src/App.tsx` — compact dashboard, route selection, title/focus handling, and root `KnowledgeBaseProvider`.
- `frontend/src/App.test.tsx` — dashboard, first-use, status reuse, Strict Mode, route, 404, workspace scope, empty state, and example-chip assertions.
- `frontend/src/Workspace.tsx` — shared shell integration, shared document scope/empty guidance, generic example chips, and SVG status/arrow icons.
- `frontend/src/Workspace.test.tsx` — contract test for the current real empty-index refusal fixture.
- `frontend/src/api/client.ts` — shared timed JSON request/error helper, document list/upload/delete methods, multipart support, status/detail preservation, and retained query normalization.
- `frontend/src/api/client.test.ts` — upload/list/delete parser and helper tests for success, duplicate, validation, gateway, network, timeout, abort, cleanup fields, and path sanitization.
- `frontend/src/api/types.ts` — document-list, upload, and deletion response types.
- `frontend/src/styles.css` — shared design tokens, shell, dashboard/library/workspace styling, touch targets, and responsive layouts.
- `frontend/src/test-fixtures/README.md` — documents real fixtures and the data-safety boundary.

New untracked frontend/report files included in the handoff:

- `HANDOFF_REPORT.md` — this report.
- `frontend/src/AppShell.tsx` — shared branding, navigation, API status, and footer.
- `frontend/src/DocumentLibrary.tsx` — PDF upload, document list, refresh, and safe deletion UI.
- `frontend/src/DocumentLibrary.test.tsx` — library state, API error, upload, duplicate, deletion, and refresh tests.
- `frontend/src/Icons.tsx` — small inline SVG icon module.
- `frontend/src/KnowledgeBaseContext.tsx` — shared health/document status provider and hook.
- `frontend/src/routing.ts` — minimal client-side navigation and upload navigation guard event.
- `frontend/src/test-fixtures/documents-empty.json` — actual empty list response.
- `frontend/src/test-fixtures/documents-empty.README.md` — empty-list fixture provenance and mutation constraint.
- `frontend/src/test-fixtures/query-empty-refusal.json` — actual empty-index query refusal response.

No dependency was added and `package.json`/lockfiles were not changed. No backend source/test, Docker file, root Dockerfile, or `data/` file was changed. The pre-existing untracked `data/` directory remains excluded from the archive.

## Backend endpoints reused

- `GET /api/health` → Vite rewrites to FastAPI `GET /health`.
- `GET /api/documents` → `GET /documents`.
- `POST /api/documents` multipart `file` → `POST /documents`.
- `DELETE /api/documents/{document_id}` → `DELETE /documents/{document_id}`.
- `POST /api/query` → `POST /query`.

The Vite proxy configuration was inspected and not changed.

## Exact commands and automated results

Baseline, before implementation:

- `npm test -- --reporter=dot` — **PASS**, 3 files and 48 tests passed.
- `npm run check` — **PASS**, `tsc --noEmit` exited 0.

Final checks after implementation:

- `npm run check` — **PASS**, `tsc --noEmit` exited 0.
- `npm test -- --reporter=dot` — **PASS**, 4 files and 81 tests passed (33 more than baseline; no unhandled errors).
- `npm run build` — **PASS**, TypeScript check passed; Vite 7.3.7 transformed 36 modules and produced the production bundle.
- `git diff --check` — **PASS**, exit 0 with no whitespace errors.
- React Strict Mode test — **PASS**, initial shared status load issued exactly two requests (one health and one list) despite development effect replay.
- Accessibility assertions use semantic roles/names, a labelled native file input, table caption, live status/alert regions, navigation `aria-current`, and native dialog semantics. No accessibility dependency was installed. A complete axe audit was not run.

Development checks during implementation briefly exposed failing assertions and one unsupported jsdom `scrollIntoView`; these were corrected. The final results above are from the passing final run.

## Live backend verification

The frontend was started with `npm run dev -- --host 127.0.0.1`. The first sandboxed bind attempt returned `listen EPERM`; the approved local Vite server then started at `http://127.0.0.1:5173/`. The live proxy requests were read-only except for the RAG query:

- `curl -sS --max-time 5 -w '\nHTTP %{http_code} elapsed=%{time_total}s\n' http://127.0.0.1:5173/api/health` — **HTTP 200**, 0.027663 s. Body: status `ok`, 0 documents, 0 chunks, manifest exists, 0 failed documents.
- `curl -sS --max-time 5 -w '\nHTTP %{http_code} elapsed=%{time_total}s\n' http://127.0.0.1:5173/api/documents` — **HTTP 200**, 0.004738 s. Body: `{ "count": 0, "documents": [] }`. This exact body is `documents-empty.json`.
- `curl -sS --max-time 150 -H 'Content-Type: application/json' -H 'Accept: application/json' -d '{"question":"What are the key topics in the indexed documents?","top_k":5}' -w '\nHTTP %{http_code} elapsed=%{time_total}s\n' http://127.0.0.1:5173/api/query` — **HTTP 200**, 0.020526 s. The real response refused (`refused: true`, `evidence.sufficient: false`) with no sources or citations. The response body is preserved in `query-empty-refusal.json`.

The initial document count was zero. No live upload, duplicate, non-PDF, oversized upload, or deletion was attempted. The backend stores uploaded PDFs, manifest records, and indexes under the repository's protected `data/` directory; Task 04 explicitly forbids modifying or deleting anything there. Even a temporary API upload would mutate that protected data, so it was not safe to perform. Therefore live upload → list → duplicate → delete → second-delete verification is **NOT VERIFIED**. Mocked UI/API tests exercise those response branches, but do not substitute for live verification. No pre-existing API documents were modified or deleted.

Fixtures captured from actual backend responses during this task are limited to the empty document-list response and empty-index refusal. Prior Task 03.1 grounded and refusal response fixtures remain included with their previously recorded sanitization/provenance. A real one-document list, upload 201, duplicate 409, wrong-file, delete 200/404, or oversized fixture was not generated or represented as real.

## Visual/responsive and accessibility verification

Visual verification at **375px, 768px, and 1280px is NOT VERIFIED**. `command -v chromium chromium-browser google-chrome google-chrome-stable firefox` returned no browser path, and `npm list --depth=0 playwright @playwright/test puppeteer` reported an empty dependency list. No browser or Playwright was installed, per instruction. Vitest/jsdom checks are not visual evidence. CSS includes narrow-card layouts and touch target sizing, but those layouts were not visually inspected.

Manual QA checklist for an environment with an existing browser:

1. At 375px, 768px, and 1280px inspect Overview, Library, and Workspace for horizontal overflow, clipping, overlap, and touch target size.
2. Inspect library empty/populated states; choose invalid signature, oversized, and valid PDFs; confirm upload waiting/stop/refresh behavior and no fake progress percentage.
3. Open/cancel/confirm the delete dialog with keyboard and Escape; test cleanup warning and focus return.
4. Navigate with links and browser back/forward; verify title, current nav, heading focus, and 404/home behavior.
5. In Workspace inspect scope disclosure, empty-base guidance, example chip focus/no auto-submit, and grounded/refusal citations with an indexed knowledge base.

## Known limitations and unverified behavior

- Backend indexing is synchronous and may block query/list/delete requests under its exclusive lock. There is no server progress, job status, cancellation, or per-document failure list. The UI reports indeterminate elapsed time and handles uncertain client outcomes honestly.
- Upload success requires an HTTP 201 response with a document object. If the connection times out or is interrupted, server work may continue; the UI retains an uncertain state and asks for a successful list refresh before allowing another upload or deletion.
- Startup-failed documents are omitted by `GET /documents`; only the health failed count can expose their number, and no row-level cleanup action is possible in this backend contract.
- Full live document mutation lifecycle and indexed-document query verification were not performed because they would modify protected `data/`.
- Browser screenshots, visual responsive checks, axe audit, Node cross-version checks, and live upload/delete workflows were not performed.
- The app does not track submitted questions or reviewed citations, so those first-run checklist items deliberately stay incomplete.

## Acceptance checklist

1. **PASS** — `/library` is linked from shared navigation, and Overview, Library, and Workspace use `AppShell`.
2. **PASS** — Client navigation, popstate back/forward, 404/home link, document title, and page-heading focus are implemented and covered by tests.
3. **NOT VERIFIED** — UI/API mock tests cover signature validation, FormData, confirmed success, five-minute timeout, and stop-waiting behavior. A live valid-PDF upload was not performed because backend uploads mutate protected `data/`.
4. **PASS** — Library implements loading, empty, error/retry, populated, refresh, optional metadata, >8-item filter, safe filename display, desktop table, and responsive card markup. Empty response was verified live; populated behavior uses API-shaped test responses.
5. **PASS** — Extension/signature/size validation plus mocked 400, 409 object duplicate, 413, 422 validation array, 504 HTML, network, and timeout branches have actionable feedback and tests.
6. **PASS** — Native confirmation, cancel, successful deletion, 404 refresh, other failure retention, repeat-request prevention, and `cleanup_required` messaging are covered with tests. Live deletion was not performed (criterion 13).
7. **PASS** — Health/list state is shared, initial fetch is deduplicated in Strict Mode and across routes, and upload/delete success invokes refresh. Mock tests assert refresh requests.
8. **PASS** — Compact operational dashboard separates API connectivity from knowledge state, shows actual supported counts, gives a zero-document upload path, safely handles null failed count, and only completes the upload checklist step with indexed-document evidence.
9. **PASS** — Workspace uses shared scope, <=10-name disclosure, empty guidance, and non-submitting example chips; prior grounding/citation/refusal/cancellation tests remain passing.
10. **PASS** — Path values are stripped from display filenames and API error text; regression tests check document, query, and error rendering.
11. **NOT VERIFIED** — Automated API/UI tests increased from 48 to 81 and include semantic accessibility assertions plus real response fixtures where safely obtainable. The complete requested real upload/delete fixture matrix and a full axe audit remain unverified because mutations to protected `data/` are prohibited and no axe package was installed.
12. **PASS** — `npm run check`, `npm test -- --reporter=dot`, and `npm run build` all pass.
13. **NOT VERIFIED** — Live health/list/query checks passed, including an honest empty-index refusal. Upload → list → duplicate → delete → second delete was not run because uploads would mutate protected `data/`; no isolated backend was available.
14. **PASS** — Branch remains `feature/organisation-knowledge-management` at baseline commit `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`; nothing is staged, committed, pushed, merged, or switched. `data/` was not touched and is excluded from the archive.

Visual/responsive verification: **NOT VERIFIED**, as described above.

## Patch and Git state

The task baseline is the current starting `HEAD`, `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`, matching the requested `fabb5b2`. `git-diff.patch` contains tracked changes from that exact baseline. `git-diff-full.patch` adds every relevant untracked frontend source, test, fixture, and this report without staging. Applicability was verified by extracting `git archive HEAD` into a temporary repository and running `git apply --check /private/tmp/ekip-task-04-handoff-staging/git-diff-full.patch`; it exited 0. No Git index changes were made.

Current Git state at report preparation:

Branch: `feature/organisation-knowledge-management`

Latest commit: `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`

Tracked diff stat:

```text
 README.md                            |   9 +-
 frontend/src/App.test.tsx            | 155 ++++++++++++++-------
 frontend/src/App.tsx                 | 258 ++++++-----------------------------
 frontend/src/Workspace.test.tsx      |  11 ++
 frontend/src/Workspace.tsx           |  28 ++--
 frontend/src/api/client.test.ts      |  85 +++++++++++-
 frontend/src/api/client.ts           | 239 ++++++++++++++------------------
 frontend/src/api/types.ts            |  29 ++++
 frontend/src/styles.css              | 215 ++++++++++++++++++++++++++++-
 frontend/src/test-fixtures/README.md |  10 +-
 10 files changed, 615 insertions(+), 424 deletions(-)
```

All Task 04 untracked frontend sources, tests, fixtures, and this report are enumerated in `untracked-inventory.txt`. `data/` appears in Git status because it was already untracked at task start; it is neither copied nor included in either patch.

## Handoff archive

Final ZIP: `/Users/joseph/Downloads/ekip-task-04-organisation-knowledge-management-handoff-final-2.zip`  
ZIP size: `532619` bytes. `unzip -t` passed; the 36-entry archive includes all relevant source, report, status and patch files, and the exclusion scan found no prohibited paths or secrets.
