# EKIP Task 07 — Test Evidence Register

Status vocabulary:
- **PASS / verified:** observed command or test output exists.
- **PENDING:** requires the persistent deployment or manual demonstration.
- **NOT RUN:** deliberately not performed by automation.

| ID | Test / evidence | Result | Evidence / notes |
|---|---|---|---|
| T07-F01 | Task 07 image build | PASS | `ekip-api:task07` built using local `ekip-api:task05.3-isolation` base. |
| T07-F02 | Runtime user | PASS | Image inspect and runtime test reported UID/GID `10001:10001`. |
| T07-F03 | Python dependency imports | PASS | FastAPI, SQLAlchemy, psycopg and Alembic imports passed. |
| T07-F04 | Offline model cache | PASS | Three cached models loaded with Docker network disabled and cache mounted read-only. |
| T07-F05 | PostgreSQL connectivity | PASS | Disposable PostgreSQL probe accepted a connection from the Task 07 image. |
| T07-F06 | Alembic migration | PASS | Disposable database reached `0006_platform_roles_and_recovery (head)`. |
| T07-F07 | API startup and health | PASS | Disposable API container passed Docker health check. |
| T07-F08 | Health endpoint | PASS | `/health` returned HTTP 200. |
| T07-F09 | Swagger and OpenAPI | PASS | `/docs` and `/openapi.json` returned HTTP 200 in isolated startup test. |
| T07-F10 | Disposable cleanup | PASS | Temporary API, PostgreSQL and network were removed. |
| T07-P01 | Docker Desktop persistent network/database setup | PENDING | Operator creates the named resources in Docker Desktop. |
| T07-P02 | Persistent deployment and verification scripts | PENDING | Run `task07_deploy.sh`, then `task07_verify.sh`. |
| T07-P03 | Swagger login and synthetic PDF upload | PENDING | Manual operator action only. |
| T07-P04 | Grounded question and answer | PENDING | Manual operator action only; requires valid OpenAI key. |
| T07-P05 | Final cleanup | PENDING | Run separate cleanup script after recording evidence. |

## Exact commands used in the verified feasibility work

The following commands were used during feasibility and validation. Some were run as part of temporary scripts; they are listed here as command evidence, not as a claim that the persistent deployment has already happened.

```bash
docker image inspect ekip-api:task07
docker run --rm --network none \
  --volume "$HOME/.cache/huggingface:/models:ro" \
  --env HF_HOME=/models \
  --env HF_HUB_OFFLINE=1 \
  --env TRANSFORMERS_OFFLINE=1 \
  ekip-api:task07 python -c "import fastapi, sqlalchemy, psycopg, alembic"
```

The disposable integration sequence used:
- a temporary Docker bridge network,
- a temporary PostgreSQL container,
- `alembic upgrade head`,
- `alembic current`,
- a temporary API container with a generated signing secret,
- HTTP checks for `/health`, `/docs` and `/openapi.json`,
- runtime UID/GID inspection,
- and explicit removal of temporary containers and network.

Recorded migration head: `0006_platform_roles_and_recovery (head)`.

## Manual evidence to append after the demonstration

| Evidence item | Actual result | Notes |
|---|---|---|
| Swagger login | PENDING | Record HTTP status only; never record password or bearer token. |
| Synthetic PDF upload | PENDING | Record synthetic filename, HTTP status and document identifier if returned. |
| Document listing | PENDING | Record expected listing result. |
| Grounded question | PENDING | Record question and concise response, excluding secrets and sensitive content. |
| Grounding/source evidence | PENDING | Record source/chunk references returned by the API. |
| Cleanup | PENDING | Confirm named containers, network and volumes are absent. |

Do not convert pending items to PASS until the corresponding output has been observed.
