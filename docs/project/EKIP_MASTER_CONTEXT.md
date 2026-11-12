# EKIP — Master Project Context

**Prepared:** 9 November 2026\
**Repository:** `/Users/joseph/enterprise-knowledge-intelligence`\
**Branch observed:** `feature/organisation-knowledge-management`\
**HEAD observed:** `9918263`

> The local Git repository remains the source of truth. This document is a continuity aid, not a replacement for source code, tests, migrations or retained task evidence.

## 1. Product identity

EKIP is an enterprise knowledge intelligence platform built around retrieval-augmented generation (RAG), evidence-constrained answers, citation validation, claim-level grounding and controlled refusal/recovery. Its implementation has expanded from a single-knowledge-base RAG workflow to include organisation/tenant isolation, identity and access management, tenant onboarding, platform administration, audit capabilities and a unified frontend.

EKIP has two integrated capability layers:

1. **Knowledge intelligence:** ingest and process documents, retrieve evidence, generate answers, validate citations and claims, and refuse when evidence cannot support a safe answer.
2. **Enterprise application and governance:** authenticate users, scope access to organisations, manage memberships and invitations, govern tenant lifecycle, provide platform administration and isolate tenant data.

The enterprise administration layer complements the RAG engine; it does not replace the grounding and evaluation capabilities that define EKIP.

## 2. Product principles confirmed by inspected implementation

- Tenant data is scoped to an organisation-specific workspace.
- Shared embedding/reranking infrastructure can be reused while tenant knowledge bases and document collections remain separate.
- Retrieval relevance is a generation gate, not proof that a question is answerable.
- Generated answers must pass citation and claim-level grounding checks.
- Uncited claims are explicitly classified, not silently treated as grounded.
- Contradictions between distinct cited sources must not be hidden by selecting only the supporting source.
- Repair is bounded and evidence-constrained.
- A grounded subset is eligible only after independent citation and grounding validation.
- Failure to establish a grounded answer results in abstention.
- Debug output that may contain tenant-confidential content is opt-in.
- Existing local changes, migrations, tests, evidence and protected deployment resources must be preserved unless a specific change is reviewed and authorized.

## 3. Confirmed technology footprint

| Area | Confirmed implementation |
|---|---|
| Backend API | Python, FastAPI |
| Frontend | React, TypeScript, Vite |
| RAG orchestration | `src/rag_pipeline.py` |
| Knowledge base | `src/knowledge_base.py` |
| Ingestion | PDF loader and text cleaner |
| Chunking | Text chunker and token-safe splitter |
| Embeddings | Embedder and shared embedder infrastructure |
| Retrieval | BM25, vector, hybrid, reciprocal-rank fusion, reranked retrieval |
| Optional retrieval backend | LlamaIndex adapter |
| Grounding | Claim parser/decomposer, evidence selector, semantic grounder, grounding evaluator |
| Citation and recovery | Citation validator, answer repair and grounded-subset fallback |
| Persistence | SQLAlchemy/Alembic identity and tenant schema; migrations 0001–0008 present |
| Tenant storage | Per-organisation workspace, manifest and upload directory |
| Deployment | Unified Docker candidate image; offline model cache support |
| Testing | pytest, integration tests, Playwright smoke tests and benchmark assets |

Exact dependency versions and complete deployment topology must be taken from current repository manifests and deployment records, not inferred here.

## 4. Repository baseline observed

- Repository: `/Users/joseph/enterprise-knowledge-intelligence`
- Branch: `feature/organisation-knowledge-management`
- HEAD: `9918263`
- Working tree: modified tracked files and numerous untracked implementation, migration, test, script, evidence and documentation files.
- `git diff --check` was clean at inspection.
- Migrations 0005–0008 were untracked at inspection and are critical candidate implementation assets. Do not discard them.
- Candidate database was verified at Alembic head `0008_invitation_lifecycle`.

This is not a clean release snapshot. Do not assume HEAD alone contains all verified implementation.

## 5. Verification baseline

Recorded full-suite result after the deterministic tampered-token test correction:

**500 passed, 4 skipped, 2 warnings in 1216.49 seconds (20:16).**

Other recorded results:
- Combined API suites: 58 passed, 1 warning.
- API acceptance suite: 38 passed, 1 warning.
- Focused platform tests: 5 passed, 33 deselected, 1 warning.
- Grounding suite: 29 passed, 1 warning.
- Task 06 browser smoke tests B-01/B-02/B-03: 3 passed.
- Earlier Task 06 pytest baseline: 148 passed.

These are historical recorded results, not proof that the repository still passes after later edits. The full run warnings included a PyTorch `torch.jit.script` warning and a Starlette HTTP 422 constant deprecation.

## 6. Protected candidate/test resources

The following resources were explicitly identified as protected during the handoff:

- Container: `ekip-unified-candidate-test-20261109`
- Image: `ekip-api:unified-candidate`
- Database: `ekip_unified_candidate_20261109`
- DB role: `ekip_unified_test_20261109`
- Tenant-data volume: `ekip_unified_candidate_tenant_data_20261109`
- PostgreSQL test container: `ekip-task05-postgres-test`
- PostgreSQL volume: `ekip_task05_pgdata`
- HF cache volume: `ekip_task04_test_hf_cache`

Do not stop, remove, rebuild, migrate, prune or otherwise alter these as part of documentation work. Do not request or expose the candidate environment file or secrets.

Candidate health checks and offline model tests do not establish production readiness.

## 7. Documentation package

- `EKIP_MASTER_CONTEXT.md` — product identity, principles and baseline.
- `EKIP_ARCHITECTURE.md` — technical components, boundaries and flows.
- `EKIP_DEVELOPMENT_STATUS.md` — completed work, test evidence, caveats and milestones.
- `EKIP_DECISION_LOG.md` — decisions evidenced by implementation and records.
- `EKIP_DEVELOPMENT_PROTOCOL.md` — engineering, testing, Git and deployment safety.

Detailed task evidence and existing repository documentation remain authoritative for their specific scope.
