# EKIP unified candidate — sandbox review notes

## What this candidate does

- Uses `ekip-api:task05.3-isolation` as the runtime dependency base.
- Does not install Python packages during the image build. The build checks that the required imports are already present and stops if the base image is incomplete.
- Copies the current backend source and Alembic migrations.
- Copies the reviewed Vite build from `frontend/dist-unified/` to `/app/frontend/dist/`.
- Serves the React application and its assets from the FastAPI process.
- Rewrites browser API requests from `/api/...` to the existing backend routes.
- Runs as UID/GID `10001`, stores tenant workspaces under `/app/data/tenants`, and expects the Hugging Face cache to be mounted read-only at `/models`.
- Keeps the image tag separate: `ekip-api:unified-candidate`. It does not replace `ekip-api:v1`, `ekip-api:task05.3-isolation`, or any other existing image.

## Local build (run on the Mac)

Run from the repository root, after applying this candidate package:

```bash
docker image inspect ekip-api:task05.3-isolation >/dev/null
test -f frontend/dist-unified/index.html
DOCKER_BUILDKIT=1 docker build \
  -f Dockerfile.unified \
  -t ekip-api:unified-candidate \
  .
```

This uses the existing local base image and normal BuildKit cache. Do not use `--no-cache`, `docker system prune`, or remove any existing images.

## Runtime requirements

The service requires:

- `EKIP_ACCESS_TOKEN_SECRET`: at least 32 bytes; supply it through your existing secret-management method, never in this document or shell history.
- `EKIP_DATABASE_URL`: a PostgreSQL SQLAlchemy URL using `postgresql+psycopg://...`.
- A writable tenant-data volume mounted at `/app/data/tenants`.
- The existing Hugging Face model-cache volume mounted read-only at `/models`.

Container environment:

```text
EKIP_TENANT_DATA_DIRECTORY=/app/data/tenants
HF_HOME=/models
HF_HUB_OFFLINE=1
TRANSFORMERS_OFFLINE=1
```

Do not run migrations against the production database as part of image verification. First test against a separate disposable database and a new isolated tenant-data volume. Do not attach the existing production tenant-data volume to a candidate test container.

## Verification still required on the Mac

The sandbox cannot see the Mac Docker daemon, the local `ekip-api:task05.3-isolation` image, or the Hugging Face cache. After the source candidate has been reviewed:

1. Confirm the base image exists locally.
2. Build the candidate image using the command above.
3. Inspect the image's runtime imports and UID/GID.
4. Run it with a newly created disposable PostgreSQL database and a new disposable tenant-data volume.
5. Mount the existing Hugging Face cache read-only at `/models`; verify the models load without network access.
6. Test `/health`, `/`, `/library`, `/workspace`, `/platform`, `/tenant/settings`, static assets, `/api/health`, authentication, tenant isolation, document upload/query and invitation lifecycle.
7. Preserve the original images, containers, volumes and production database. Do not promote the candidate tag until all acceptance checks pass.

## Sandbox test boundary

The sandbox passed the focused auth/tenant/frontend subset and a broader set of unit tests. The full suite could not be run here because this environment does not include the RAG/model dependencies (`faiss`, `sentence-transformers`, `openai`) and the upload intentionally omitted the local `data/evaluation/benchmarks` files. The frontend package install could not be completed offline because an npm tarball was absent from the sandbox cache and the sandbox Node version is below the project's declared engine minimum. These are environment limitations, not reported as passing tests.
