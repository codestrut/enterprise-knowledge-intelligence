# Repository instructions

## EKIP Implementation and Handoff Standard

This standard is mandatory for implementation work across backend, frontend, database, security, testing, infrastructure, and documentation. Before editing, read [the detailed implementation and handoff standard](docs/engineering/IMPLEMENTATION_HANDOFF_STANDARD.md) and follow its workflow and deliverables.

Preserve existing work and task boundaries. Do not stage, commit, push, reset, clean, stash, switch branches, overwrite unrelated reports or original roadmap documents, or touch production resources without explicit authorization. Verify only with appropriate isolated resources, report actual evidence and unresolved criteria, and do not claim completion from test results alone.

For completed implementation tasks, update the task-specific handoff and status materials and prepare the validated review archive described in the detailed standard. Respect a task-specific instruction not to package, and do not package instruction-only changes as product implementations.

## Usage-Efficient Engineering Workflow

Apply this workflow to every task alongside the standard above. Efficiency never permits skipping essential checks, weakening security or tests, hiding failures, or lowering required quality. Where this workflow and another rule conflict, follow the stricter rule.

1. **Diagnose once, with evidence.** Make one focused diagnosis from the relevant files, logs and existing reports before editing. Do not repeat baseline inspection already completed in the same task.
2. **Implement the smallest complete change.** Fix the demonstrated root cause fully. Do not build speculative alternatives or add dependencies the task does not require.
3. **Reuse valid work.** Reuse earlier findings, scripts and test results while the code and inputs they cover are unchanged. Label reused results as historical, and re-run any whose inputs changed.
4. **Verify focused first.** Run the checks that directly cover the change first. Broaden testing only when risk, changed shared interfaces or contracts, or failures justify it. Record checks not run and why.
5. **Keep output lean.** Inspect targeted files and line ranges, and filter or summarise verbose tool output. Limit intermediate updates to decisions, blockers and results. This does not reduce the required final handoff content.
6. **Define done before starting.** State explicit acceptance criteria and a stopping condition. Stop when they are met or when a blocker needs user input, and do not begin adjacent work.
7. **Report honestly.** Report only tests actually run, with their real results, failures, skips, limitations and remaining work.
8. **Preserve boundaries.** All security, task-boundary, user-change and Git restrictions above remain in force.
