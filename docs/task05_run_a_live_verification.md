# Task 05 Run A — completing the live-container and browser checks

Run A (2026-10-17) verified the audit fixes with unit, TestClient/API, PostgreSQL integration, Vitest, type-check and production-build evidence. Two checks are **NOT VERIFIED** because the owner chose Option C:

- rebuilding a test API container from the Run A tree; and
- running Playwright against it, including live login, logout, token revocation and multi-organisation sign-in.

Option C forbids stopping, removing, rebuilding or modifying `ekip-api-test`, and forbids touching its volumes `ekip_task04_test_data` and `ekip_task04_test_hf_cache`.

This procedure completes those checks in a **genuinely isolated environment**: a separate machine or VM with its own Docker engine, or this machine only after the owner explicitly decides what happens to `ekip-api-test`. The existing Playwright and Vite configurations only accept an API on loopback port **8001**, and that port is occupied here by `ekip-api-test`.

## Safety rules (unchanged)

- Never use the production container `ekip-api`, port 8000, or the `ekip_data` volume. Read-only status commands are the only exception.
- Never mount or copy the repository `data/` directory. Never open or print `.env`. Generate synthetic secrets in the process environment and never echo them.
- Create only resources with distinct, run-specific names, and remove only resources created by this procedure.
- Do not enable multiple Uvicorn workers. Throttling counters and locks are per-process.

## Required configuration (deployment-compatibility change)

From Run A, the API **refuses to start** unless `EKIP_ACCESS_TOKEN_SECRET` holds at least 32 bytes (B4). Every environment that runs this code needs it, including any future rebuild of production. Optional settings:

| Variable | Default | Purpose |
|---|---|---|
| `EKIP_ACCESS_TOKEN_SECRET` | none, so startup fails | HMAC signing key; at least 32 bytes; never commit or print it |
| `EKIP_ARGON2_MAX_CONCURRENCY` | `4` | Cap on simultaneous Argon2 verifications (1–16); invalid values stop startup |
| `EKIP_ENABLE_API_DOCS` | off | Enables `/docs`, `/redoc` and `/openapi.json`; isolated development or test only, never production |
| `EKIP_DEBUG_RETRIEVAL_LOGGING` | off | Enables `[RAG DEBUG]` diagnostics, which include question text; development only |

## Procedure (isolated host)

1. **Preflight.** Confirm that the names and the port are free, and stop if any are already in use:
   ```sh
   docker ps -a --format '{{.Names}}' | grep -E '^ekip-task05-runa-' || true
   docker volume ls --format '{{.Name}}' | grep -E '^ekip_task05_runa_' || true
   lsof -nP -iTCP:8001 -sTCP:LISTEN || true
   ```
2. **Isolated PostgreSQL.** Start a dedicated database. The suite requires a name containing `test`.
   ```sh
   export PGPASSWORD_RUNA="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
   docker volume create ekip_task05_runa_pgdata
   docker run -d --name ekip-task05-runa-postgres -p 127.0.0.1:55433:5432 \
     -e POSTGRES_USER=ekip_runa -e POSTGRES_PASSWORD="$PGPASSWORD_RUNA" -e POSTGRES_DB=ekip_runa_test \
     -v ekip_task05_runa_pgdata:/var/lib/postgresql/data postgres:16-alpine
   ```
3. **Build a run-specific image** from the Run A tree. Do not reuse an existing tag.
   ```sh
   docker build -t ekip-task05-runa-api:test .
   ```
4. **Migrate and bootstrap synthetic identities.** Use the test database URL, passed only through the environment.
   - Create one single-organisation reader or contributor.
   - Create one account with two active memberships, for the F3 flow. Use `--allow-existing-org` for the second organisation's administrator only when that is genuinely intended.
5. **Run the API on loopback port 8001** with new volumes. Keep secrets out of command lines and `docker inspect` output: write them to a permission-restricted env file **outside the repository** and never print it.
   ```sh
   umask 077
   python3 - "$PGPASSWORD_RUNA" > ~/ekip-task05-runa-api.env <<'PY'
   import secrets, sys
   print("EKIP_ACCESS_TOKEN_SECRET=" + secrets.token_urlsafe(48))
   print("EKIP_DATABASE_URL=postgresql+psycopg://ekip_runa:" + sys.argv[1] + "@host.docker.internal:55433/ekip_runa_test")
   PY
   docker volume create ekip_task05_runa_tenants
   docker run -d --name ekip-task05-runa-api -p 127.0.0.1:8001:8000 \
     --env-file ~/ekip-task05-runa-api.env \
     -v ekip_task05_runa_tenants:/app/data/tenants ekip-task05-runa-api:test
   ```
   Delete `~/ekip-task05-runa-api.env` during cleanup. Limitation: an env file keeps secrets out of command lines and shell history, but container environment values (including `POSTGRES_PASSWORD` from step 2) remain readable by anyone who can run `docker inspect` on that host. Use a single-user isolated host, or Docker secrets on a shared one.
   Confirm startup refusal as well: run the same image once **without** `EKIP_ACCESS_TOKEN_SECRET`. The container must exit with a `Startup refused: EKIP_ACCESS_TOKEN_SECRET …` log line, and no session rows may be written.
6. **Playwright** (from `frontend/`; the config refuses anything except loopback 8001):
   ```sh
   EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 \
   EKIP_E2E_LOGIN_EMAIL=<single-org synthetic> EKIP_E2E_LOGIN_PASSWORD=<synthetic> \
   EKIP_E2E_MULTI_ORG_EMAIL=<multi-org synthetic> EKIP_E2E_MULTI_ORG_PASSWORD=<synthetic> \
   npm run test:e2e
   ```
   Supply credentials from a file outside the repository, for example through `set -a; . ~/ekip-runa-e2e.env; set +a`. Never print that file. Expected results:
   - **Proxy smoke:** the unauthenticated `/api/auth/me` returns 401, and there is no `/api/documents` request before sign-in.
   - **Live login:** profile shown, logout returns 204, and the revoked access token returns 401.
   - **Multi-organisation:** selection is offered without retyping the password, the second login carries `organisation_id`, and the profile matches the chosen organisation.
   - **Workspace flow:** passes.
7. **Manual browser spot checks.**
   - Sign in as A, open the library and workspace, sign out, then sign in as B. None of A's filenames or answers may appear (F1).
   - Login errors show only fixed text (F4).
   - Repeated wrong passwords return the throttling message, and the account still works from another client address (B1).
8. **Evidence and cleanup.** Save `docker logs ekip-task05-runa-api` after checking it contains no question text or `[RAG DEBUG]`. Then remove **only** `ekip-task05-runa-api`, `ekip-task05-runa-postgres`, `ekip_task05_runa_tenants`, `ekip_task05_runa_pgdata` and the `ekip-task05-runa-api:test` image.

Record each result as PASS, FAIL or NOT VERIFIED in the Run A section of `HANDOFF_REPORT_TASK05.md`.
