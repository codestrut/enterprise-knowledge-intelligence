# EKIP Task 07 — Personal Execution Runbook

This is an operator runbook, separate from the formal task deliverables. Use macOS Terminal first. Do not run destructive commands against existing Task 05/06 resources.

## 1. Open the repository

```bash
cd ~/enterprise-knowledge-intelligence
git status --short
```

Review the working tree. Do not reset, clean, stash, or overwrite existing changes.

## 2. Install the Task 07 package files

Copy the supplied `scripts/task-07/` and `docs/task-07/` directories into the repository. Keep the existing `Dockerfile.task07` unchanged unless a later inspection identifies a specific defect.

Make scripts executable:

```bash
chmod +x scripts/task-07/*.sh
```

## 3. Prepare protected environment configuration

```bash
./scripts/task-07/task07_prepare.sh
```

Expected:
- Docker Desktop and the local `ekip-api:task07` image are detected.
- The three previously verified model-cache directories are present.
- Port 8004 is free.
- `.env.task07` is created with mode 600, or an existing file is preserved.
- No Docker network, volume or container is created by this script.

If `.env.task07` reports an empty `OPENAI_API_KEY`, add a valid key locally using a secure editor. Do not paste it into chat, task documents, shell history or screenshots. Keep `.env.task07` out of version control.

## 4. Manually create Docker resources in Docker Desktop

Open Docker Desktop → **Containers** / **Volumes** / **Networks** as applicable. UI labels can vary by Docker Desktop release.

Create the following resources:

### 4.1 Network

- Name: `ekip-task07-net`
- Driver: `bridge`

### 4.2 PostgreSQL volume

- Name: `ekip-task07-postgres-data`

### 4.3 PostgreSQL container

- Image: `postgres:16-alpine` (already available locally).
- Container name: `ekip-task07-postgres`.
- Network: `ekip-task07-net`.
- Mount: `ekip-task07-postgres-data` → `/var/lib/postgresql/data`.
- Environment:
  - `POSTGRES_DB`
  - `POSTGRES_USER`
  - `POSTGRES_PASSWORD`

Use the exact values from `.env.task07`. Do not substitute a new password unless you also update the database URL in that file. Do not publish a host port; the API reaches PostgreSQL over the isolated Docker network.

To copy each value to the macOS clipboard without printing it, run the relevant command in Terminal, then paste into the corresponding Docker Desktop field:

```bash
grep '^POSTGRES_DB=' .env.task07 | cut -d= -f2- | pbcopy
grep '^POSTGRES_USER=' .env.task07 | cut -d= -f2- | pbcopy
grep '^POSTGRES_PASSWORD=' .env.task07 | cut -d= -f2- | pbcopy
```

After creating the container, confirm in Docker Desktop that it is running and attached to `ekip-task07-net`.

## 5. Deploy

```bash
./scripts/task-07/task07_deploy.sh
```

The script:
1. Checks that the manually created resources exist and PostgreSQL is accepting connections.
2. Runs `alembic upgrade head`.
3. Prints the migration head.
4. Runs the existing organisation bootstrap command.
5. Prompts securely for the administrator password; enter it twice if requested.
6. Creates the disposable tenant-data volume if absent.
7. Starts the API container with loopback-only port mapping and the read-only model cache.

Expected endpoints:
- Health: `http://127.0.0.1:8004/health`
- Swagger: `http://127.0.0.1:8004/docs`

If bootstrap reports that the organisation or identity already exists, stop and inspect the database/bootstrap state. Do not add flags to bypass safeguards or reset credentials without reviewing the state.

## 6. Verify deployment

```bash
./scripts/task-07/task07_verify.sh
```

Expected:
- Docker health status becomes `healthy`.
- `/health`, `/docs` and `/openapi.json` return HTTP 200.
- Runtime UID is 10001.
- Host port is bound to `127.0.0.1:8004`.
- API and PostgreSQL share the Task 07 network.
- `/models` is mounted read-only.
- Alembic reports the expected head.

If the API is still loading models, allow the configured health-check start period and rerun verification. If it fails, inspect only the Task 07 logs:

```bash
docker logs --tail 120 ekip-task07-api
docker logs --tail 120 ekip-task07-postgres
```

Do not post environment values or tokens in shared evidence.

## 7. Manual Swagger demonstration — operator only

Automation intentionally does not perform these actions.

1. Open `http://127.0.0.1:8004/docs`.
2. Use the existing API login endpoint and the administrator credentials created during bootstrap.
3. Authorize Swagger using the returned access token. Never save or publish the token.
4. Upload a newly created synthetic PDF using the existing document upload endpoint.
5. Confirm the upload response and document listing.
6. Submit a question answerable from the synthetic PDF using the existing query endpoint.
7. Record HTTP statuses, document identifier, concise answer and returned source/grounding references in the evidence register.
8. Do not use existing tenant documents or real personal/confidential data.

Use the request schemas displayed by this running Swagger/OpenAPI instance. Do not rely on guessed JSON payloads. A valid `OPENAI_API_KEY` is required for answer generation; API health alone does not prove the model-provider request works.

## 8. Cleanup — run only after evidence is recorded

First inspect the cleanup targets. Then:

```bash
./scripts/task-07/task07_cleanup.sh --confirm
```

The cleanup removes only:
- `ekip-task07-api`
- `ekip-task07-postgres`
- `ekip-task07-net`
- `ekip-task07-tenant-data`
- `ekip-task07-postgres-data`
- `.env.task07`

It retains:
- `ekip-api:task07` and all other Docker images
- Docker build cache and base images
- Hugging Face model cache
- source code and existing repository changes
- Task 07 scripts, reports and evidence

## 9. Post-cleanup verification

```bash
docker ps -a --filter name=ekip-task07
docker network ls --filter name=ekip-task07
docker volume ls --filter name=ekip-task07
docker image inspect ekip-api:task07 >/dev/null && echo "Task 07 image retained"
test -d "$HOME/.cache/huggingface" && echo "Model cache retained"
git status --short
```

The Task 07 runtime resources should be absent; the image and model cache should remain. Review the Git status to confirm previous work remains intact.
