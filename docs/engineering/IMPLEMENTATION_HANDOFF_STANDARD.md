# EKIP Implementation and Handoff Standard

This guide defines the default engineering workflow and review handoff for implementation tasks in this repository. Apply it to backend, frontend, database, security, testing, infrastructure, and documentation changes. Task-specific user constraints and repository safety boundaries still apply; the narrower safe scope takes precedence.

## 1. Preserve the working tree and task boundaries

Before editing:

- Identify the repository root and current branch.
- Inspect `git status --short`, staged and unstaged diffs, relevant source/tests, and relevant untracked files. Do not repeat baseline checks unnecessarily during a continuing task.
- Read applicable `AGENTS.md` guidance and task-specific handoffs. Look for existing reports, templates, standards, and roadmap references before creating replacements.
- Preserve unrelated and uncommitted work. Do not stage, commit, push, reset, clean, stash, or switch branches without explicit user authorization.
- Never overwrite an unrelated task report or an original master checklist/roadmap document without explicit authorization. Prefer a task-specific report or separate status addendum.
- Respect architecture, security boundaries, migrations, compatibility, task sequencing, and accepted roadmap decisions. Do not begin later roadmap work without instruction.

## 2. Implement the requested scope

- Inspect the relevant implementation, tests, configuration, and callers before making changes.
- Fix the demonstrated root cause. Keep changes focused; do not add unrelated refactors, features, or dependencies.
- Explain significant design choices and note migration, compatibility, data-retention, and rollback implications where applicable.
- Preserve existing tests and assertions. Do not weaken tests to obtain a pass.
- Never expose credentials, tokens, secrets, local environment values, or protected user data in command output, reports, fixtures, or archives.

## 3. Verify with evidence

- Select relevant unit, integration, security, frontend, browser, type-check, build, and diff checks for the change. Run expensive or broad checks only when appropriate; record checks not run and why.
- Use isolated test databases, containers, volumes, API ports, documents, and identities for experimental or live verification. Do not use production resources for destructive or experimental checks.
- Before mutating a test service, inspect its actual configuration and resource boundaries. Clean up only resources created by the test, using scoped procedures that preserve existing records and auditability.
- Record exact commands, working directory/environment, and actual outcomes, including pass/fail/skip counts, warnings, and failures. Redact secrets from output.
- Distinguish freshly executed checks from historical results, mocks, source review, manual observation, and live integration. Historical results must not be presented as newly run.
- Never invent results, metrics, logs, or evidence. If a prerequisite is missing, report the exact blocker and do not substitute a mock while claiming live verification.
- Run `git diff --check` when applicable. Inspect the final diff and Git status; verify that only the intended files changed.

## 4. Required implementation handoff

For each completed implementation, create or update a task-specific handoff report without overwriting unrelated reports. Reconcile every major claim against current source, diffs, and test evidence. Include:

1. **Executive summary:** objective, delivered scope, verified state, remaining work, and closure recommendation.
2. **Architecture and implementation:** relevant components, routes/interfaces, data flow, decisions, migration and compatibility notes.
3. **Changed-file inventory:** created, modified, removed, and untracked relevant files; distinguish this task's work from pre-existing changes when the diff combines them.
4. **Security and safety assessment:** tested controls, source-review observations, threat boundaries, production/test separation, and untested assumptions.
5. **Verification evidence:** exact commands and actual results, purpose, environment, warnings, failures, skips, and checks not performed.
6. **Acceptance matrix:** criterion, implementation evidence, verification method, result (`PASS`, `FAIL`, or `NOT VERIFIED`), outstanding issue, and closure state.
7. **Known limitations and blockers:** severity, consequence, and specific next action; separate release blockers from follow-up improvements.
8. **Gate/task decision:** explicit status with rationale. Passing automated tests alone does not establish completion.
9. **Git snapshot:** branch, current commit, `git status --short`, and `git diff --stat`; confirm staged/commit/push state without changing it.
10. **Continuation instructions:** next task or action, first steps, relevant files/services/commands, environmental constraints, and roadmap continuity.

Update task status or roadmap references through a separate addendum if original checklist/roadmap sources are absent or must remain untouched. Clearly distinguish complete, partial, blocked, and unverified items. Do not mark a later task implemented unless it was actually started and evidenced.

## 5. Review archive for completed implementations

Unless task-specific instructions say otherwise, prepare a clearly named, versioned ZIP for external review. Do not create a product-implementation archive for instruction-only or documentation-configuration tasks unless requested. Use existing packaging conventions only if they satisfy these requirements; otherwise create a dedicated temporary staging area and archive.

Include, as relevant:

- The comprehensive task handoff and a standalone detailed Markdown implementation report.
- An acceptance/test evidence matrix, status/roadmap addendum, source-change inventory, continuation instructions, and archive README.
- A safe tracked Git patch and current Git status snapshot. Document included untracked source separately because it is absent from ordinary Git diffs.
- Relevant source, tests, and non-sensitive fixtures needed for review.
- A PDF report when a reliable available converter can generate it and the result can be validated; otherwise omit it and state why.

Exclude `.git`, environment files, credentials, secrets, tokens, database dumps, production or local document data, uploaded PDFs, model/dependency caches, virtual environments, build output, and unrelated repository/user files. Do not blindly archive the repository. Scan the staged file list before zipping.

After creating the ZIP, verify it is non-empty, test ZIP integrity, list/inspect its contents, confirm required deliverables and source are present, and confirm prohibited files/directories are absent. Use a new versioned filename if a target already exists; never overwrite an existing archive. Verify and report the exact output path and size. If a deliverable cannot be created safely, state why and provide the remaining artifacts without claiming success.

## 6. Final response

Report the actual task status, important verified results, unresolved blockers and unverified criteria, changed files, handoff/archive paths, and the precise next action. State clearly if verification or packaging was not performed. Preserve all safety constraints and stop at the requested boundary.
