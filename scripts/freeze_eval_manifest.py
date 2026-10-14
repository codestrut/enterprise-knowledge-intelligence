#!/usr/bin/env python3
"""Write a reproducibility manifest for the current EKIP evaluation setup.

This captures configuration and dataset fingerprints only. It does not run the
RAG pipeline, save generated answers, or include raw corpus text.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.evaluation.retrieval_eval import EVALUATION_DATASET  # noqa: E402

CORPUS_DEFAULT = "data/raw/nist_csf_2.0.pdf"
PIPELINE_FILES = [
    "scripts/run_framework_eval.py",
    "src/evaluation/retrieval_eval.py",
    "src/rag_pipeline.py",
    "src/generation/prompt_builder.py",
    "src/generation/answer_repair.py",
    "src/generation/grounding_evaluator.py",
    "src/generation/semantic_grounder.py",
    "src/retrieval/retriever.py",
    "src/retrieval/hybrid_retriever.py",
    "src/retrieval/reranked_retriever.py",
    "src/retrieval/reranker.py",
]
PACKAGES = [
    "torch",
    "transformers",
    "sentence-transformers",
    "huggingface-hub",
    "faiss-cpu",
    "llama-index-core",
    "ragas",
    "pypdf",
    "tiktoken",
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True,
            text=True, timeout=5,
        )
        return result.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def file_fingerprint(relative_path: str) -> dict[str, Any]:
    path = ROOT / relative_path
    record: dict[str, Any] = {"path": relative_path, "exists": path.is_file()}
    if path.is_file():
        record["sha256"] = sha256_file(path)
        record["size_bytes"] = path.stat().st_size
    return record


def package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def build_manifest(corpus_relative: str) -> dict[str, Any]:
    dataset = list(EVALUATION_DATASET)
    dataset_payload = json.dumps(
        dataset, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")

    corpus_path = ROOT / corpus_relative
    corpus_record: dict[str, Any] = {
        "path": corpus_relative,
        "exists": corpus_path.is_file(),
    }
    if corpus_path.is_file():
        corpus_record["sha256"] = sha256_file(corpus_path)
        corpus_record["size_bytes"] = corpus_path.stat().st_size
    else:
        corpus_record["note"] = "Corpus fingerprint unavailable; verify the path before comparing runs."

    status = git_value("status", "--porcelain") or ""
    changed_paths = []
    for line in status.splitlines():
        # Git status entries start with a two-character status code and a path.
        changed_paths.append(line[3:] if len(line) > 3 else line)

    return {
        "schema_version": 1,
        "freeze_name": "ekip-mvp-eval-baseline-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "packages": package_versions(),
        },
        "git": {
            "commit": git_value("rev-parse", "HEAD"),
            "branch": git_value("branch", "--show-current"),
            "working_tree_dirty": bool(changed_paths),
            "changed_paths": changed_paths,
            "note": "Dirty state is recorded, not rejected; local uncommitted work is preserved.",
        },
        "corpus": corpus_record,
        "evaluation_dataset": {
            "module": "src/evaluation/retrieval_eval.py",
            "query_count": len(dataset),
            "answerable_count": sum(bool(item.get("answerable")) for item in dataset),
            "unanswerable_count": sum(not bool(item.get("answerable")) for item in dataset),
            "sha256": sha256_bytes(dataset_payload),
            "items": dataset,
        },
        "pipeline_files": [file_fingerprint(path) for path in PIPELINE_FILES],
        "recommended_run_commands": {
            "custom": "python scripts/run_framework_eval.py --backend custom --report reports/framework-poc/custom-full-anchor-labels.json",
            "llamaindex": "python scripts/run_framework_eval.py --backend llamaindex --report reports/framework-poc/llamaindex-full-anchor-labels.json",
        },
        "limits": [
            "This manifest fingerprints the configuration and labelled query dataset; it is not a response replay bundle.",
            "The current evaluation cases do not yet encode requester identity or per-user ACL permissions.",
            "Do not compare reports if corpus hash, dataset hash, key pipeline hashes, or runtime model settings differ without documenting the difference.",
            "The manifest stores file paths and hashes, not corpus text, API keys, tokens, or environment-variable values.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", default=CORPUS_DEFAULT, help="Corpus path relative to the project root.")
    parser.add_argument(
        "--out", default="reports/evaluation/ekip-mvp-baseline-v1-manifest.json",
        help="Manifest path relative to the project root.",
    )
    parser.add_argument("--force", action="store_true", help="Replace an existing manifest at --out.")
    args = parser.parse_args()

    output = (ROOT / args.out).resolve()
    if output.exists() and not args.force:
        parser.error(f"Manifest already exists: {output}. Use --force only when intentionally re-freezing.")

    manifest = build_manifest(args.document)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Manifest written: {output.relative_to(ROOT)}")
    print(f"Queries: {manifest['evaluation_dataset']['query_count']} "
          f"(answerable={manifest['evaluation_dataset']['answerable_count']}, "
          f"unanswerable={manifest['evaluation_dataset']['unanswerable_count']})")
    print(f"Dataset SHA-256: {manifest['evaluation_dataset']['sha256']}")
    print(f"Corpus fingerprint available: {manifest['corpus']['exists']}")
    print(f"Git working tree dirty: {manifest['git']['working_tree_dirty']}")
    if not manifest["corpus"]["exists"]:
        print("WARNING: corpus path not found; rerun with --document pointing at the active evaluation corpus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
