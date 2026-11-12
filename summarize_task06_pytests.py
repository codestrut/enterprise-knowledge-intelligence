#!/usr/bin/env python3
"""Inventory and optionally collect/run the EKIP Task 06 focused pytest suites.

Default mode is read-only and AST-based: it does not import application modules,
connect to a database, start services, or execute tests. --collect performs
pytest collection only for a selected safe unit-test group. --run executes only
one of the explicitly allow-listed unit-test groups. PostgreSQL/API/E2E tests
are inventoried but are never run by this script.
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
import shlex
from pathlib import Path
from typing import Iterable

CORE_MODULES = {
    "tests/unit/test_auth_permissions.py": "Platform and organisation permissions / role boundaries",
    "tests/unit/test_auth_migration.py": "Authentication schema and migration-chain invariants",
    "tests/unit/test_auth_models.py": "Identity, membership, role relationships and database constraints",
    "tests/unit/test_auth_service.py": "Authentication, persisted membership permissions and session lifecycle",
    "tests/unit/test_task06_contracts.py": "Task 06 onboarding, approval, role and recovery request contracts",
    "tests/unit/test_task06_tenant_lifecycle.py": "Tenant lifecycle transitions and activation preconditions",
    "tests/unit/test_task06_tenant_onboarding_service.py": "Tenant registration, idempotency, approval, provisioning and retry service behaviour",
}

SUPPORT_MODULES = {
    "tests/unit/test_auth_access_tokens.py": "Access-token claims, expiry and malformed-token rejection",
    "tests/unit/test_auth_bootstrap.py": "Safe/repeatable organisation and platform-admin bootstrap",
    "tests/unit/test_auth_database.py": "Explicit database URL configuration validation (no connection by these tests)",
    "tests/unit/test_auth_passwords.py": "Password policy, Argon2 hashing and verification",
    "tests/unit/test_auth_throttling.py": "Sign-in failure throttling and Argon2 concurrency cap logic",
}

RELATED_NOT_DEFAULT = {
    "tests/unit/test_tenant_storage.py": "Tenant workspace storage isolation; collection requires its ML dependency set",
    "tests/api/test_api_acceptance.py": "API acceptance suite; imports application startup/dependency stack",
    "tests/integration/test_auth_postgres.py": "PostgreSQL auth, refresh/revocation, schema and concurrency integration",
    "tests/integration/test_authenticated_query_tenant_isolation.py": "Authenticated query tenant-boundary integration",
    "tests/integration/test_rag_tenant_retrieval_isolation.py": "RAG retrieval tenant-isolation integration",
    "tests/integration/test_real_tenant_index_isolation.py": "Real index tenant isolation integration",
}


def python_test_declarations(path: Path) -> tuple[list[str], str | None]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [], str(exc)
    names = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    ]
    return sorted(names), None


def print_group(root: Path, title: str, group: dict[str, str], show_tests: bool) -> tuple[int, int]:
    print(f"\n{title}")
    present = 0
    declarations = 0
    for rel, purpose in group.items():
        path = root / rel
        if not path.is_file():
            print(f"  MISSING  {rel}")
            continue
        present += 1
        names, error = python_test_declarations(path)
        declarations += len(names)
        print(f"  FOUND    {rel} | declarations={len(names)}")
        print(f"           Purpose: {purpose}")
        if error:
            print(f"           AST_ERROR: {error}")
        elif show_tests:
            for name in names:
                print(f"             - {name}")
    print(f"  Summary: {present}/{len(group)} files found; {declarations} Python test-function declarations")
    return present, declarations


def selected_groups(which: str) -> list[dict[str, str]]:
    if which == "core":
        return [CORE_MODULES]
    if which == "support":
        return [SUPPORT_MODULES]
    return [CORE_MODULES, SUPPORT_MODULES]


def run_pytest(root: Path, which: str, collect_only: bool) -> int:
    modules: list[str] = []
    for group in selected_groups(which):
        modules.extend(group.keys())
    missing = [module for module in modules if not (root / module).is_file()]
    if missing:
        print("Cannot run selected suite; required files are missing:")
        for item in missing:
            print(f"  - {item}")
        return 2
    command = [sys.executable, "-m", "pytest", "-q"]
    if collect_only:
        command.append("--collect-only")
    command.extend(modules)
    print("\nExecution command (allow-listed unit-test files only):", flush=True)
    print(" ".join(command), flush=True)
    print(f"Working directory: {root}", flush=True)
    completed = subprocess.run(command, cwd=root, check=False)
    if collect_only:
        label = "COLLECTION" if completed.returncode == 0 else "COLLECTION BLOCKED/FAILED"
    else:
        label = "TEST RUN" if completed.returncode == 0 else "TEST RUN FAILED/BLOCKED"
    print(f"\n{label} exit code: {completed.returncode}")
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize EKIP Task 06 pytest implementation and optionally collect/run the safe focused unit suites."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root (defaults to current directory).")
    parser.add_argument("--show-tests", action="store_true", help="List every test_* function declaration in each inventoried file.")
    parser.add_argument("--collect", choices=("core", "support", "combined"), help="Run pytest --collect-only for an allow-listed unit suite.")
    parser.add_argument("--run", choices=("core", "support", "combined"), help="Run an allow-listed unit suite. Does not run API/PostgreSQL/browser tests.")
    args = parser.parse_args()
    if args.collect and args.run:
        parser.error("choose either --collect or --run, not both")

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"ERROR: repository root does not exist: {root}", file=sys.stderr)
        return 2

    print("EKIP Task 06 — pytest implementation inventory")
    print(f"Repository root: {root}")
    print("Default mode is source inventory only; it does not execute tests or connect to services.")

    core_found, core_decl = print_group(root, "CORE TASK 06 UNIT SUITE", CORE_MODULES, args.show_tests)
    support_found, support_decl = print_group(root, "SUPPORTING AUTH UNIT SUITE", SUPPORT_MODULES, args.show_tests)
    related_found, related_decl = print_group(root, "RELATED / SEPARATE VALIDATION GATES (NOT RUN BY DEFAULT)", RELATED_NOT_DEFAULT, args.show_tests)

    print("\nSUMMARY")
    print(f"  Core modules: {core_found}/{len(CORE_MODULES)} present; {core_decl} test-function declarations")
    print(f"  Supporting auth modules: {support_found}/{len(SUPPORT_MODULES)} present; {support_decl} test-function declarations")
    print(f"  Related separate-gate modules: {related_found}/{len(RELATED_NOT_DEFAULT)} present; {related_decl} test-function declarations")
    print("  Note: Python function declarations are not the same as collected pytest cases; parametrization may increase collection counts.")
    print("\nRECOMMENDED COMMANDS")
    script_path = shlex.quote(str(Path(__file__).expanduser().resolve()))
    root_path = shlex.quote(str(root))
    print(f"  Core collection:  python3 {script_path} --root {root_path} --collect core")
    print(f"  Run core suite:   python3 {script_path} --root {root_path} --run core")
    print(f"  Run support:      python3 {script_path} --root {root_path} --run support")
    print(f"  Run combined:     python3 {script_path} --root {root_path} --run combined")
    print(f"  List test names:  python3 {script_path} --root {root_path} --show-tests")
    print("\nSAFETY: API acceptance, PostgreSQL integration, tenant-storage/ML dependencies and Playwright are separate gates. They are inventoried only and are not started by this script.")

    if args.collect:
        return run_pytest(root, args.collect, collect_only=True)
    if args.run:
        return run_pytest(root, args.run, collect_only=False)
    missing_core = len(CORE_MODULES) - core_found
    missing_support = len(SUPPORT_MODULES) - support_found
    return 1 if missing_core or missing_support else 0


if __name__ == "__main__":
    raise SystemExit(main())
