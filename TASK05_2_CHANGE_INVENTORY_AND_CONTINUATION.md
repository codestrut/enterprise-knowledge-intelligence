# Task 05.2 Change Inventory and Continuation Notes

## Repository snapshot

- Branch: `feature/organisation-knowledge-management`
- Commit: `fabb5b2c0d591a6408da2ec7ac66feeb5d69298b`
- Worktree: dirty; no staged changes.
- Aggregate tracked diff at review start: 22 files, 1,955 insertions, 1,080 deletions. This includes Task 04 and prior Task 05 work; it is not a Task 05.2-only count.
- Latest RAG verification changed no application source, tests, frontend, Docker files, or repository data.

## Significant implementation paths

### Identity and security

`src/auth/{models.py,permissions.py,passwords.py,access_tokens.py,service.py,dependencies.py,database.py,bootstrap.py}`; `src/api/main.py`; migrations `0001_identity_foundation.py` through `0004_scoped_security_audit.py`.

### Tenant document and RAG

`src/api/tenant_storage.py`, `src/api/shared_inference.py`, `src/knowledge_base.py`, `src/rag_pipeline.py`, `src/retrieval/reranked_retriever.py`.

### Frontend and tests

Frontend auth/login/library/API client/context, browser E2E `frontend/e2e/smoke.spec.ts`, and relevant frontend unit tests/fixtures. Backend tests include `tests/api/test_api_acceptance.py`, auth and tenant unit tests, RAG evidence/citation tests, and `tests/integration/test_auth_postgres.py`.

### Task 04 and mixed baseline

Task 04 frontend/browser work remains uncommitted alongside Task 05. Do not attribute the aggregate diff only to Task 05.2. The Task 04 `HANDOFF_REPORT.md` is preserved. The untracked `data/` directory was not inspected or included in the archive.

## Services and constraints

- Isolated API: `127.0.0.1:8001`, container `ekip-api-test`, image `ekip-api:task05.2-test`.
- Isolated PostgreSQL: `127.0.0.1:55432`, container `ekip-task05-postgres-test`, database `ekip_auth_test`, revision `0004_scoped_security_audit`.
- Isolated API volumes: `ekip_task04_test_data:/app/data` and `ekip_task04_test_hf_cache:/root/.cache/huggingface`.
- Production: port 8000, container `ekip-api`, volume `ekip_data`. Do not request or mutate this service for Task 05 review.
- Never include `.env`, credentials, database URLs, access/refresh tokens, local document data, model cache, `node_modules`, build outputs, or `.git` in review artifacts.

## Reproduction commands

From project root, focused safe backend regressions:

```sh
.venv/bin/python -m pytest tests/api/test_api_acceptance.py tests/unit/test_evidence_gate.py tests/unit/test_citation_validator.py tests/unit/test_answer_repair.py tests/unit/test_grounding_evaluator.py tests/unit/test_grounding_evaluator_uncited.py tests/unit/test_grounding_relation_guard.py tests/unit/test_grounding_support_integration.py tests/unit/test_grounding_validator.py tests/unit/test_tenant_storage.py -q
```

The latest result was 72 passed in 45.76s. The broader KnowledgeBase/evaluation tests that open `data/raw/nist_csf_2.0.pdf` were intentionally not run in the latest continuation.

PostgreSQL integration requires the established guarded wrapper to supply `EKIP_TEST_DATABASE_URL` internally from the isolated test service. Do not print its URL/credentials. Direct pytest without that variable deliberately skips module collection and exits 5.

From `frontend/`, if a rerun is needed:

```sh
npm test -- --reporter=dot
npm run check
npm run build
EKIP_API_PROXY_TARGET=http://127.0.0.1:8001 npm run test:e2e
```

The Playwright configuration is designed to fail if the API target uses production port 8000.

## Resume sequence

1. Review the consolidated `HANDOFF_REPORT_TASK05.md` and acceptance matrix.
2. If reviewers request fresh aggregate results, rerun the relevant suites using the isolated environment, distinguishing latest command output from historical output.
3. Do not remove synthetic PostgreSQL identities/audit rows through broad cleanup: they remain for attribution. Any cleanup should be narrowly scoped and preserve audit integrity.
4. After review, close Task 05.2 and start Task 06 as a separate task. Task 06's configurable metadata framework remains planned and unimplemented.
