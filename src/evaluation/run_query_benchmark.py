"""CLI for running a JSON query suite through a supplied pipeline factory.

Example:
python -m src.evaluation.run_query_benchmark \
  --suite data/evaluation/benchmarks/customer_suite.json \
  --factory examples.ekip_rag_pipeline_factory:build_pipeline \
  --report reports/customer-suite.json
"""

from __future__ import annotations

import argparse
import importlib
from collections.abc import Callable, Mapping
from typing import Any

from src.evaluation.document_independent_benchmark import (
    load_suite,
    run_query_benchmark,
    write_report,
)


def load_factory(reference: str) -> Callable[[Mapping[str, Any]], Any]:
    """Load a factory using ``package.module:function`` notation."""
    if ":" not in reference:
        raise ValueError("Factory must use module.path:function notation.")
    module_name, function_name = reference.split(":", 1)
    if not module_name or not function_name:
        raise ValueError("Factory must use module.path:function notation.")
    module = importlib.import_module(module_name)
    factory = getattr(module, function_name, None)
    if not callable(factory):
        raise ValueError(f"Factory {reference!r} is not a callable.")
    return factory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run EKIP's corpus-agnostic query benchmark."
    )
    parser.add_argument("--suite", required=True, help="Human-reviewed JSON query suite.")
    parser.add_argument(
        "--factory",
        required=True,
        help="Pipeline factory reference in module.path:function format.",
    )
    parser.add_argument("--report", required=True, help="Output JSON report path.")
    args = parser.parse_args(argv)

    try:
        suite = load_suite(args.suite)
        if not suite.get("query_cases"):
            parser.error("The provided suite contains no query_cases.")
        factory = load_factory(args.factory)
        report = run_query_benchmark(suite, factory)
        destination = write_report(report, args.report)
    except (ImportError, AttributeError, TypeError, ValueError) as exc:
        parser.error(str(exc))

    metrics = report["metrics"]
    print(f"Suite: {report['suite_id']}")
    print(f"Queries: {metrics['query_count']}")
    print(f"Answer success: {metrics['answer_success_rate']}")
    print(f"Refusal accuracy: {metrics['refusal_accuracy']}")
    print(f"Citation validity: {metrics['citation_validity_rate']}")
    print(f"Grounded claim rate: {metrics['grounded_claim_rate']}")
    print(f"Report: {destination}")

    gates = report["acceptance_gates"]
    if not gates["configured"]:
        print("Acceptance gates: none configured; report is diagnostic only.")
        return 0
    for check in gates["checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(
            f"{status} {check['metric']} {check['operator']} {check['expected']} "
            f"(actual={check['actual']})"
        )
    return 0 if gates["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
