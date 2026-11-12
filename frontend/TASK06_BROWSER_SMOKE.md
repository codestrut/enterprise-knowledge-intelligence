# EKIP Task 06 isolated platform browser smoke

This test exercises the Task 06 platform-administration UI against an in-memory
mock API. It is intended to verify UI rendering, browser routing, form flows,
API client request construction, and permission-driven controls without touching
production, PostgreSQL, Docker tenant volumes, real user accounts, or real
credentials.

## Requirements

- Node.js matching the `engines` requirement in `package.json`.
- Frontend dependencies installed with `npm ci`.
- Playwright Chromium installed (`npx playwright install chromium`) if not already installed.
- Python 3; the mock server uses only the Python standard library.
- Loopback ports 8003 and 5174 free.

## Run

From the repository root:

```bash
cd frontend
npx playwright test --config=playwright.task06-smoke.config.ts
```

Playwright starts a synthetic API mock on `127.0.0.1:8003` and the Vite frontend
on `127.0.0.1:5174`, then stops both when the run completes. If either port is
occupied, the run fails instead of reusing an existing process. Do not stop or
modify another process to free these ports without identifying it first.

The mock uses `example.test` identities and in-memory records. It does not import
the EKIP backend or connect to any database. The Vite config proxies the browser's
same-origin `/api/...` requests to the mock and strips the `/api` prefix. The
spec asserts that browser-side API requests remain on `127.0.0.1:5174`, not the
production port 8000 or tenant test API port 8002.

## Scope and limitations

The test covers the platform admin page, synthetic tenant directory states,
registration creation, user search, platform role assignment, approval, stale
recovery and retry UI. Mock responses do **not** prove server authorization,
PostgreSQL constraints, migration safety, transactionality, or concurrency. Those
remain separate backend/integration gates.
