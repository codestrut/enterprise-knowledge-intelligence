# EKIP unified candidate — sandbox review report

## Review status

**Source candidate: reviewed and unit-tested within the available sandbox.**
**Docker image: not built here.**
**Production readiness: not yet approved.**

The uploaded archive was ZIP-integrity checked and extracted to an isolated workspace. The original local Mac repository, Docker images, containers, volumes and databases were not accessed or changed.

## Changes prepared

1. Added `src/api/unified_frontend.py` to serve the built React application and static assets, and rewrite `/api/...` requests to the existing FastAPI routes.
2. Updated `src/api/main.py` to register that unified frontend handler and serve `frontend/dist`.
3. Added `tests/unit/test_unified_frontend.py` for SPA page routing, API-prefix rewriting and static assets.
4. Hardened canonical Base64URL decoding in `src/auth/access_tokens.py`. The previous decoder could accept a different final Base64URL character when only unused pad bits changed, meaning a textually altered token could decode to the same signature bytes.
5. Added a regression test in `tests/unit/test_auth_access_tokens.py`.
6. Added `Dockerfile.unified`, based on `ekip-api:task05.3-isolation`, with no pip install step. It verifies required Python imports, copies the current source/migrations and frontend build, runs as UID/GID 10001, and keeps tenant data separate from the read-only model cache.
7. Added `UNIFIED_DEPLOYMENT.md` with the local build and safe verification requirements.

## Verification completed

| Check | Result |
|---|---:|
| Focused auth, invitation, tenant-lifecycle and frontend tests | 92 passed |
| Filtered broader unit suite | 297 passed |
| Python source compilation (`compileall`) | Passed |
| Alembic migration head | `0008_invitation_lifecycle` |
| Built frontend HTML asset references | Both JS and CSS files present |
| ASGI smoke test using actual `dist-unified` files | `/`, `/library`, JS asset and `/api/health` returned HTTP 200 |
| Edited-file whitespace scan | Clean |

The 92-test focused run overlaps with the 297-test filtered run; they are not additive counts.

## Checks not completed and why

- **Full Python suite:** not run to completion. The sandbox does not contain the RAG runtime packages (`faiss`, `sentence-transformers`, `openai`) needed to collect several RAG/model test modules. The archive also intentionally omitted `data/evaluation/benchmarks/cross_domain_grounding.json`, which two additional unit-test modules need. The filtered unit suite excluded those modules; no claim is made that the full suite passed.
- **Frontend rebuild / Vitest / Playwright:** not run. Sandbox Node is `v22.16.0`, below the project's declared minimum `v22.22.2`; `npm ci --offline` also stopped because `yallist-3.1.1` was not in the sandbox npm cache. The already-built `frontend/dist-unified` bundle was smoke-tested through the ASGI app.
- **Docker build / runtime / offline model loading:** not run. The sandbox cannot access the Mac Docker daemon, local `ekip-api:task05.3-isolation` image or the user's Hugging Face cache. The Dockerfile has a fail-fast dependency import check, but the image still needs to be built and exercised locally.
- **Database migration execution:** not run. Only the migration head was inspected. No database was connected or changed.

## Local acceptance gates before promotion

1. Build `ekip-api:unified-candidate` from the existing `ekip-api:task05.3-isolation` base.
2. Verify imports, UID/GID, and the `/app/frontend/dist` assets in the built image.
3. Run with a **new disposable PostgreSQL database** and a **new disposable tenant-data volume**.
4. Mount the existing Hugging Face cache read-only at `/models` and verify all required models load with offline mode enabled.
5. Exercise authentication, tenant isolation, documents, query, platform/tenant administration, invitations, browser routes and API routes.
6. Preserve all existing images, containers, volumes and production data. Do not run the Task 07 cleanup script, Docker prune, or production migrations as part of this candidate test.

**Decision:** suitable for controlled local candidate-image testing after the patch is applied; not yet a production release.
