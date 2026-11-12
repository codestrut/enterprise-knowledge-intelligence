# EKIP — Architecture and Engineering Decision Log

**Prepared:** 9 November 2026\
**Purpose:** Record decisions evidenced by inspected implementation and handoff records. This is a retrospective baseline, not a claim that every item was formally approved through an ADR process.

## DEC-001 — Organisation-scoped knowledge workspaces

**Status:** Observed in implementation.\
**Decision:** Maintain a separate workspace, upload directory, manifest, knowledge base, chunk collection and retriever for each organisation.\
**Rationale:** Tenant content and retrieval state remain scoped to the organisation; shared embedding/reranking infrastructure can be reused without merging tenant knowledge collections.\
**Evidence:** `src/api/tenant_storage.py`, `src/knowledge_base.py`.\
**Follow-up:** Verify persistence, backup/restore, retention and deletion against formal requirements.

## DEC-002 — Shared inference infrastructure with tenant-scoped knowledge bases

**Status:** Observed in implementation.\
**Decision:** Reuse shared embedding/reranking dependencies while creating tenant-specific knowledge-base and retrieval state.\
**Rationale:** Avoid unnecessary duplication of model infrastructure while retaining tenant separation at the knowledge-workspace boundary.\
**Evidence:** `TenantWorkspaceRegistry`, `TenantWorkspace`, shared embedder and reranker initialization.\
**Follow-up:** Verify concurrency, resource isolation and lifecycle behavior under multi-tenant load.

## DEC-003 — Evidence relevance gate before generation

**Status:** Observed in implementation.\
**Decision:** Apply a relevance threshold before calling the LLM; missing, unusable or unscored evidence fails closed.\
**Rationale:** Avoid generation when retrieval has not produced sufficiently relevant evidence.\
**Evidence:** `src/generation/evidence_gate.py`, `src/rag_pipeline.py`.\
**Current threshold:** `4.3`, described as calibrated against NIST CSF 2.0 and a starting threshold, not universal.\
**Follow-up:** Calibrate across domains, retrievers and model changes.

## DEC-004 — Separate citation validity from semantic grounding

**Status:** Observed in implementation.\
**Decision:** Validate citation source identifiers separately from claim-level semantic support.\
**Rationale:** A citation can point to an existing source without that source supporting the claim.\
**Evidence:** `citation_validator.py`, `grounding_evaluator.py`, `rag_pipeline.py`.

## DEC-005 — Atomic claim-level grounding

**Status:** Observed in implementation.\
**Decision:** Parse and decompose answer claims, select evidence from cited sources and evaluate semantic relations at atomic-claim level.\
**Rationale:** Whole-answer checks can conceal unsupported clauses within otherwise supported text.\
**Evidence:** `claim_parser.py`, `claim_decomposer.py`, `evidence_selector.py`, `semantic_grounder.py`, `grounding_evaluator.py`.\
**Follow-up:** Evaluate decomposition quality and error rates across document types.

## DEC-006 — Conservative contradiction handling

**Status:** Observed in implementation.\
**Decision:** Require contradiction prediction, high contradiction confidence, relevant evidence and meaningful content overlap before classifying contradiction. Do not let support from one distinct cited source hide a strong contradiction from another.\
**Rationale:** Reduce spurious contradiction labels while preserving cross-source disagreements.\
**Evidence:** `GroundingEvaluator` thresholds and `_classify_claim()`.\
**Follow-up:** Test conflicting versions, effective dates, source authority and numeric/negation cases.

## DEC-007 — Bounded answerability recovery and grounding repair

**Status:** Observed in implementation.\
**Decision:** Attempt constrained recovery when the initial draft abstains despite passing relevance, and constrained repair when citations or grounding fail.\
**Rationale:** Relevant retrieval may still be answerable even if the first draft abstains; a defective draft may be repairable without introducing new facts.\
**Evidence:** `answer_repair.py`, `rag_pipeline.py`.\
**Follow-up:** Measure repair acceptance, false recovery and repeated-abstention rates.

## DEC-008 — Grounded-subset salvage must be independently revalidated

**Status:** Observed in implementation.\
**Decision:** If repair fails, construct a candidate only from evaluator-approved grounded atomic claims, copy rather than rewrite them, attach an existing source number, then rerun citation and grounding checks.\
**Rationale:** Preserve a smaller useful answer only when it independently satisfies the same acceptance controls.\
**Evidence:** `build_grounded_subset_answer()` and its caller in `rag_pipeline.py`.\
**Follow-up:** Preserve regression tests for source conflicts, invalid citations, duplicates and partial support.

## DEC-009 — Fail-closed final answer behavior

**Status:** Observed in implementation.\
**Decision:** If recovery, repair or independent subset validation does not pass, return the explicit abstention response.\
**Rationale:** Unsupported output is not preferable to a safe refusal.\
**Evidence:** `answer_passes_grounding()`, `rag_pipeline.py`.\
**Follow-up:** Monitor false refusals as well as unsupported-answer rates.

## DEC-010 — Explicit organisation and platform authorization scopes

**Status:** Observed in implementation.\
**Decision:** Separate organisation membership roles from platform role assignments and permission bundles.\
**Rationale:** Platform governance authority is distinct from a user's role within a tenant.\
**Evidence:** `src/auth/models.py`, `src/auth/permissions.py`, API route inventory.\
**Platform roles:** super administrator, tenant creator, tenant approver, provisioning operator.\
**Organisation roles:** organisation administrator, contributor, reader.\
**Follow-up:** Review legacy `is_platform_admin` compatibility and every route's scope enforcement.

## DEC-011 — Durable tenant onboarding and invitation lifecycle

**Status:** Observed in implementation.\
**Decision:** Persist tenant onboarding/provisioning state and invitation lifecycle rather than treating tenant creation as one transient request.\
**Rationale:** Provisioning, approval, retry/recovery and initial administrator invitation require durable state and idempotency.\
**Evidence:** `TenantOnboarding`, `OrganisationInvitation`, migrations 0005–0008, platform and tenant API routes.\
**Follow-up:** Verify state transitions, idempotency, concurrency and downgrade safety.

## DEC-012 — Tenant workspace manifest restoration

**Status:** Observed in implementation.\
**Decision:** Restore tenant document state from UUID-scoped directories and manifests while ignoring unrelated/legacy files and guarding against symlinks/path escape.\
**Rationale:** Recovery must not import arbitrary files or cross tenant boundaries.\
**Evidence:** `TenantWorkspaceRegistry.restore_all()`, `restore_workspace()` and manifest helpers.\
**Follow-up:** Test crash consistency, corrupted manifests, partial restores and filesystem permissions.

## DEC-013 — Sensitive diagnostics are opt-in

**Status:** Observed in implementation.\
**Decision:** Avoid content-bearing query, answer, prompt and retrieved-text logs by default; gate detailed debugging behind explicit environment flags.\
**Rationale:** Retrieved material and generated content may contain tenant-confidential information.\
**Evidence:** `src/rag_pipeline.py`, `answer_repair.py`.\
**Follow-up:** Review log sinks, retention, access control and production configuration.

## DEC-014 — Candidate deployment is not production approval

**Status:** Observed in deployment documentation and handoff.\
**Decision:** Treat unified Docker deployment and associated database/resources as candidate/test infrastructure.\
**Rationale:** Candidate health checks and model smoke tests do not establish operational readiness or production migration approval.\
**Evidence:** `Dockerfile.unified`, `UNIFIED_DEPLOYMENT.md`, recorded candidate verification.\
**Follow-up:** Define release gate, production topology, backup/restore, monitoring and rollback.

## DEC-015 — Preserve working tree and evidence

**Status:** Established in implementation handoff standard.\
**Decision:** Do not reset, clean, stash, switch branches, stage, commit, push or delete files/resources without explicit authorization and review. Preserve regression tests, evidence, protected databases/containers/volumes and permanent source assets.\
**Rationale:** The working tree contains substantial implementation and untracked assets that cannot safely be classified by Git status alone.\
**Evidence:** `docs/engineering/IMPLEMENTATION_HANDOFF_STANDARD.md` and project handoff instructions.\
**Follow-up:** Use read-only inventory before changes and narrowly scoped cleanup only after classification and approval.

## Open decision topics

The inspected evidence does not establish final decisions for production database topology/high availability, tenant encryption/key management, retention/deletion/export policy, external identity provider/SSO, multi-worker throttling, production observability/incident response, LLM provider/failover, or formal release/security acceptance criteria.

Create separate ADRs when these are researched and approved. Do not silently treat open topics as settled.
