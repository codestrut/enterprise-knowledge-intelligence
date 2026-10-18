"""Organisation-scoped document storage and in-memory retrieval indexes.

Each organisation gets a separate manifest, upload directory, chunk collection,
and retriever. The shared embedder instance is reused; legacy global documents
are never imported into a tenant workspace.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import UUID

from src.api.document_records import manifest_record, resolve_stored_path
from src.api.document_fingerprints import sha256_file
from src.api.rwlock import ReadWriteLock


logger = logging.getLogger(__name__)


@dataclass
class TenantWorkspace:
    organisation_id: UUID
    root: Path
    upload_directory: Path
    manifest_path: Path
    knowledge_base: Any
    pipeline: Any | None
    pipeline_factory: Any
    pipeline_dependencies: dict[str, Any]
    lock: ReadWriteLock
    pipeline_lock: Lock

    def get_pipeline(self):
        with self.pipeline_lock:
            if self.pipeline is None:
                self.pipeline = self.pipeline_factory(
                    knowledge_base=self.knowledge_base,
                    **self.pipeline_dependencies,
                )
                self.pipeline.tenant_id = self.organisation_id
            return self.pipeline

    def read_manifest(self) -> dict[str, dict[str, Any]]:
        if not self.manifest_path.exists():
            return {}
        try:
            with self.manifest_path.open("r", encoding="utf-8") as source:
                payload = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("Tenant document manifest cannot be read.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("documents", {}), dict):
            raise RuntimeError("Tenant document manifest has an invalid shape.")
        documents = payload.get("documents", {})
        return {
            key: value
            for key, value in documents.items()
            if isinstance(key, str) and isinstance(value, dict)
        }

    def write_manifest(self, documents: dict[str, dict[str, Any]]) -> None:
        temporary = self.manifest_path.with_name(f".{self.manifest_path.name}.tmp")
        try:
            with temporary.open("w", encoding="utf-8") as destination:
                json.dump({"documents": documents}, destination, indent=2, ensure_ascii=False)
                destination.write("\n")
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)


class TenantWorkspaceRegistry:
    """Lazily create and restore isolated workspaces for validated UUIDs."""

    def __init__(
        self,
        root: str | Path,
        *,
        shared_embedder: Any,
        shared_reranker: Any | None = None,
        pipeline_dependencies: dict[str, Any] | None = None,
        knowledge_base_factory,
        pipeline_factory,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.shared_embedder = shared_embedder
        self.shared_reranker = shared_reranker
        self.pipeline_dependencies = dict(pipeline_dependencies or {})
        self.knowledge_base_factory = knowledge_base_factory
        self.pipeline_factory = pipeline_factory
        self._workspaces: dict[UUID, TenantWorkspace] = {}
        self._lock = Lock()

    def workspace_for(self, organisation_id: UUID) -> TenantWorkspace:
        try:
            tenant_id = UUID(str(organisation_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError("Invalid organisation scope.") from None
        if tenant_id != organisation_id:
            raise ValueError("Organisation scope must be a canonical UUID.")
        with self._lock:
            current = self._workspaces.get(tenant_id)
            if current is not None:
                return current
            self.root.mkdir(parents=True, exist_ok=True)
            tenant_root = self.root / str(tenant_id)
            if tenant_root.is_symlink():
                raise ValueError("Tenant storage path is invalid.")
            tenant_root.mkdir(mode=0o700, exist_ok=True)
            resolved = tenant_root.resolve()
            if not resolved.is_relative_to(self.root):
                raise ValueError("Tenant storage path is invalid.")
            upload_directory = resolved / "uploads"
            upload_directory.mkdir(mode=0o700, exist_ok=True)
            knowledge_base = self.knowledge_base_factory(
                embedder=self.shared_embedder,
                reranker=self.shared_reranker,
            )
            # The service derives this ID from the authenticated membership.
            knowledge_base.tenant_id = tenant_id
            workspace = TenantWorkspace(
                organisation_id=tenant_id,
                root=resolved,
                upload_directory=upload_directory,
                manifest_path=resolved / "documents_manifest.json",
                knowledge_base=knowledge_base,
                pipeline=None,
                pipeline_factory=self.pipeline_factory,
                pipeline_dependencies=self.pipeline_dependencies,
                lock=ReadWriteLock(),
                pipeline_lock=Lock(),
            )
            self._workspaces[tenant_id] = workspace
            return workspace

    def restore_all(self) -> None:
        """Restore only UUID-named tenant directories and their own manifests."""
        if not self.root.exists():
            return
        for path in sorted(self.root.iterdir()):
            if path.is_symlink() or not path.is_dir():
                continue
            try:
                organisation_id = UUID(path.name)
            except ValueError:
                # Leave unrelated/legacy files untouched and quarantined.
                continue
            workspace = self.workspace_for(organisation_id)
            self.restore_workspace(workspace)

    @staticmethod
    def restore_workspace(workspace: TenantWorkspace) -> None:
        documents = workspace.read_manifest()
        restored: dict[str, dict[str, Any]] = {}
        for document_id, saved in documents.items():
            try:
                source_path = resolve_stored_path(workspace.upload_directory, document_id)
                if not source_path.is_file():
                    raise FileNotFoundError(source_path.name)
                workspace.knowledge_base.add_pdf(
                    file_path=source_path,
                    document_id=document_id,
                )
                # add_pdf returns a copy; update the live record and its chunks so the
                # original filename survives restarts in listings, downloads and citations.
                record = workspace.knowledge_base.documents[document_id]
                if "filename" in saved:
                    set_original_filename(workspace.knowledge_base, document_id, saved["filename"])
                record["status"] = "indexed"
                record["sha256"] = saved.get("sha256") or sha256_file(source_path)
                restored[document_id] = manifest_record(document_id, record)
            except Exception as exc:
                logger.exception("Tenant document restore failed (%s).", type(exc).__name__)
                restored[document_id] = manifest_record(
                    document_id,
                    {**saved, "status": "failed", "error": type(exc).__name__},
                )
        workspace.write_manifest(restored)


def set_original_filename(knowledge_base: Any, document_id: str, filename: str) -> None:
    """Replace the stored UUID filename with the user's original filename in the live index."""
    knowledge_base.documents[document_id]["filename"] = filename
    for chunk in knowledge_base.chunks:
        metadata = chunk.get("metadata", {})
        if metadata.get("document_id") == document_id:
            metadata["filename"] = filename


@contextmanager
def tenant_workspace_lock(workspace: TenantWorkspace, *, write: bool):
    lock = workspace.lock.write_lock() if write else workspace.lock.read_lock()
    with lock:
        yield
