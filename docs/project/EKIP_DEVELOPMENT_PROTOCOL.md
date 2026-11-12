# EKIP — Development and Change-Control Protocol

**Prepared:** 9 November 2026\
**Repository source of truth:** `/Users/joseph/enterprise-knowledge-intelligence`

## 1. Purpose

This protocol governs future EKIP engineering work so changes remain traceable, testable and safe. The local repository is the source of truth. ChatGPT Project documents provide continuity and planning context; they do not replace local source, Git history or retained execution evidence.

## 2. Non-negotiable preservation rules

Unless the user explicitly authorizes a specific action after reviewing its impact:

- Do not reset, clean, stash, switch branches, stage, commit or push.
- Do not overwrite existing files or replace user changes.
- Do not delete untracked files merely because they are untracked.
- Do not apply patches/diffs without reviewing contents and target state.
- Do not remove `.bak` files before determining whether they contain unique recovery evidence.
- Do not remove or rewrite migrations.
- Do not run broad Docker prune, volume prune, system prune or wildcard deletion commands.
- Do not alter protected candidate/test databases, containers or volumes during unrelated work.
- Do not expose secrets, environment files, tokens, passwords or database URLs.
- Do not run migrations against production or an unverified database.
- Do not claim to have accessed or modified the user's local Mac repository. The user runs local commands and supplies output.

## 3. Working environment and baseline

Observed environment:
- macOS on Apple Silicon M2.
- Repository: `/Users/joseph/enterprise-knowledge-intelligence`.
- Branch: `feature/organisation-knowledge-management`.
- HEAD at handoff: `9918263`.

Confirm state before a new implementation task:

```bash
cd /Users/joseph/enterprise-knowledge-intelligence

printf '\n========== REPOSITORY IDENTITY ==========\n'
pwd
git branch --show-current
git rev-parse --short HEAD

printf '\n========== WORKING TREE ==========\n'
git status --short

printf '\n========== DIFF VALIDATION ==========\n'
git diff --check
```

This is inventory/validation only. Do not follow it with cleanup or staging unless explicitly authorized.

## 4. Engineering workflow

1. **Define scope:** exact behavior, affected component and acceptance criteria.
2. **Inspect before editing:** implementation, related tests, migrations and task documentation.
3. **Classify assets:** permanent source, migrations, tests, evaluation assets, evidence, historical backups and disposable test artifacts.
4. **Plan minimal change:** prefer the smallest additive change that satisfies the requirement.
5. **Preserve compatibility:** identify API, database, tenant, frontend and migration impacts.
6. **Implement:** make only agreed changes.
7. **Test narrowly first:** run focused tests relevant to the change.
8. **Run broader tests when justified:** use full suite for broad-impact changes or release checkpoint.
9. **Inspect the diff:** review exact changed files and `git diff --check`.
10. **Report evidence:** commands, environment, timestamps, duration, pass/fail/skip counts and warnings.
11. **Clean up only with authorization:** identify exact disposable resources, verify each action, preserve permanent tests/evidence.
12. **Handoff:** record changes, non-changes, test results, residual risks and next action.

## 5. Testing rules

- Never claim a test passed unless actual output supports it.
- Distinguish collection from execution.
- Distinguish unit, API, integration, browser, benchmark and deployment verification.
- Use isolated test databases/resources for destructive or migration tests.
- Never run integration tests against protected candidate or production databases.
- Preserve regression tests for fixed defects.
- Do not weaken assertions merely to obtain a green test.
- For token/signature tampering tests, ensure the mutation deterministically changes the value.
- Record skipped tests and warnings.
- Re-run the smallest relevant test set after a narrow change; run the full suite when impact warrants it.
- Treat historical results as historical; a new source change may invalidate the prior checkpoint.

Recorded baseline: `500 passed, 4 skipped, 2 warnings in 1216.49s`. This is historical, not a standing guarantee.

## 6. Database and migration safety

Before a migration task:
- Inspect the complete revision chain and both upgrade/downgrade functions.
- Identify destructive operations and data-loss implications.
- Confirm target database identity without exposing credentials.
- Use an isolated disposable database for migration tests.
- Preserve the protected candidate database and role.
- Never run downgrade/destructive migration tests against candidate/production databases.
- Verify schema state after tests and preserve logs.

Migrations 0005–0008 were untracked at the inspected baseline but are critical implementation assets. Preserve them.

## 7. Tenant isolation and security review

Changes touching tenant-sensitive behavior must consider:
- Authentication scope.
- Organisation membership and role.
- Platform role versus tenant role.
- Tenant ID propagation through API dependencies and services.
- Tenant workspace registry and filesystem path validation.
- Document list, upload, query, download and delete boundaries.
- Invitation and onboarding transitions.
- Audit event scope.
- Sensitive content in logs/debug diagnostics.
- Concurrency and shared inference behavior.

Frontend visibility is not an authorization boundary. Verify backend authorization.

## 8. RAG quality and evaluation review

Changes touching retrieval or generation must preserve the layered acceptance model:

1. Evidence relevance gate.
2. Citation identifier validation.
3. Claim parsing and decomposition.
4. Evidence selection from cited sources.
5. Semantic grounding.
6. Contradiction and source-conflict handling.
7. Bounded repair/recovery.
8. Independent validation of grounded-subset fallback.
9. Fail-closed abstention.

Do not lower thresholds, relax grounding acceptance or bypass citation validation merely to improve answer rate. Evaluate false refusals and unsupported-answer rates together.

Benchmark changes must record dataset/version, query set, model, retrieval backend, threshold, metrics and comparison against prior baseline.

## 9. Logging and sensitive information

- Keep content-bearing diagnostics disabled by default.
- Treat `EKIP_DEBUG_RETRIEVAL_LOGGING` and `EKIP_DEBUG_GENERATION_DETAILS` as sensitive debugging controls.
- Do not paste secrets, environment files, tokens, passwords, database URLs or confidential tenant documents into project documentation.
- Use synthetic or sanitized content for reproducible tests where possible.
- Ensure logs/evidence do not disclose tenant-confidential content unnecessarily.

## 10. Docker and candidate deployment safety

Candidate resources listed in `EKIP_MASTER_CONTEXT.md` are protected. Do not alter them as a side effect of unrelated work.

Before deployment:
- Confirm exact image, container, network, database, role and volume identities.
- Inspect deployment scripts and commands before execution.
- Confirm target environment and data impact.
- Separate build, migration, run, health-check and rollback steps.
- Do not run broad prune commands.
- Do not claim candidate validation is production readiness.
- Obtain explicit approval before production deployment or migration.

## 11. Evidence and reporting standard

Each verification report should include:
- Task identifier and scope.
- Repository branch and commit.
- Working-tree state.
- Environment versions.
- Exact command executed.
- Start/end timestamp and duration when available.
- Test collection count.
- Passed, failed, skipped and warning counts.
- Initial failure diagnostics, if any.
- Correction and files changed.
- Retest command and exact output.
- Deployment/database/resource identities, where relevant.
- Cleanup actions and verification, if authorized.
- Final decision: pass, fail, partial, blocked or not run.

Never fabricate output or reconstruct missing evidence as if it were captured.

## 12. ChatGPT Project workflow

Recommended conversation areas:
1. Product architecture and system design.
2. Backend, APIs and database.
3. Authentication, security and governance.
4. RAG engine, retrieval and evaluation.
5. Frontend and user experience.
6. Infrastructure, deployment and DevOps.
7. QA, verification and release management.

At the start of a workstream, reference relevant project documents and exact local repository baseline. At handoff, update status/decision records only after evidence is available.

## 13. Definition of done

A task is complete only when:
- Agreed behavior is implemented.
- Relevant tests pass or exceptions are documented.
- Tenant/security and migration impacts are reviewed where applicable.
- Diff is inspected and whitespace validation is clean.
- No unauthorized destructive action occurred.
- Evidence is retained.
- Remaining risks and follow-up work are stated.
