# EKIP Task 07 — Implementation Report

## Objective

Improve the security and deployment readiness of the existing EKIP document-grounding API through a targeted deployment-hardening change, focused verification, and Docker deployment preparation while preserving the existing application architecture and repository changes.

## Scope and operating boundary

- Use the existing FastAPI application (`src.api.main:app`) and existing Alembic migrations.
- Use a dedicated Task 07 Docker image and isolated Docker network/database.
- Run the API as non-root UID/GID `10001:10001`.
- Mount the existing Hugging Face model cache read-only and configure offline model loading.
- Keep Swagger enabled only in this isolated demonstration environment.
- Demonstrate PDF ingestion and grounded question-answering manually through Swagger using synthetic content only.
- Automated scripts do not upload PDFs or submit grounded questions.
- Cleanup removes only Task 07 runtime resources and generated Task 07 environment secrets.

## Implementation decisions

1. Preserve the repository's existing `Dockerfile`, `.dockerignore`, application code and previous task changes.
2. Build `Dockerfile.task07` on the locally available `ekip-api:task05.3-isolation` dependency image to avoid reinstalling pinned dependencies.
3. Use PostgreSQL 16 Alpine, the existing `postgresql+psycopg` SQLAlchemy driver and the existing Alembic migration chain.
4. Bind the API to `127.0.0.1:8004` on the host.
5. Require an explicit `EKIP_ACCESS_TOKEN_SECRET` and `EKIP_DATABASE_URL`.
6. Keep the model cache read-only at `/models`; set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1`.
7. Keep the OpenAI key outside the image and inject it through `.env.task07`.

## Verified implementation evidence

The following have been observed in disposable feasibility tests:

- `ekip-api:task07` built successfully from the local dependency base image.
- Image configuration reports user `10001:10001` and work directory `/app`.
- Required database and API dependencies imported successfully.
- PostgreSQL connectivity from the Task 07 image passed.
- Alembic migrations completed and reported `0006_platform_roles_and_recovery (head)`.
- The API container passed its Docker health check.
- `/health`, `/docs` and `/openapi.json` returned HTTP 200 in the isolated startup test.
- Runtime identity inside the API container was UID/GID `10001:10001`.
- All three cached embedding/reranking models loaded with network access disabled and the cache mounted read-only.
- Temporary feasibility containers, network and database resources were removed after testing.

## Targeted security improvement

The Task 07 image runs the API as an unprivileged user and mounts the host model cache read-only. The image includes a Docker health check against `/health`. The API is published only on the host loopback interface for the local demonstration. Existing application-level signing-key validation remains active and rejects startup when `EKIP_ACCESS_TOKEN_SECRET` is not configured adequately.

## Deployment configuration

- Docker network: `ekip-task07-net`
- PostgreSQL container: `ekip-task07-postgres`
- PostgreSQL volume: `ekip-task07-postgres-data`
- API container: `ekip-task07-api`
- Tenant data volume: `ekip-task07-tenant-data`
- API host binding: `127.0.0.1:8004`
- Swagger UI: `http://127.0.0.1:8004/docs`

## Manual demonstration boundary

The operator manually authenticates in Swagger, uploads a synthetic PDF, and submits a grounded question. No production or existing tenant documents are used. The scripts in `scripts/task-07/` do not perform those actions.

## Limitations and pending evidence

- Persistent Docker Desktop resources have not yet been created by the operator.
- The final persistent deployment and manual Swagger demonstration remain pending.
- A successful health check does not prove that OpenAI answer generation works. A valid `OPENAI_API_KEY` is required for the grounded-answer demonstration.
- The final document-ingestion and grounded-answer results must be recorded only after the manual demonstration.
- This local demonstration configuration is not a production deployment profile; Swagger is enabled and host access is intentionally loopback-only.

## Cleanup

Run `scripts/task-07/task07_cleanup.sh --confirm` after the manual demonstration. It removes the Task 07 API and PostgreSQL containers, Task 07 network, database and tenant-data volumes, and `.env.task07`. It deliberately retains Docker images/build cache, the Hugging Face cache, repository code, scripts, documentation and evidence.
