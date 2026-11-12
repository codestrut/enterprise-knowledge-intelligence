"""Static safety gates for the proposed Phase 1 migration 0007.

These tests do not apply or downgrade a database migration. They guard two
review findings that must be resolved before an operator approves execution.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION_PATH = ROOT / "migrations" / "versions" / "0007_tenant_invitations_and_settings.py"


def _load_migration():
    spec = importlib.util.spec_from_file_location("phase1_migration_0007", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase1_migration_revision_fits_default_alembic_version_column():
    migration = _load_migration()
    # Alembic's default version table declares version_num as VARCHAR(32).
    assert len(migration.revision) <= 32, (
        f"Revision ID is {len(migration.revision)} characters; "
        "shorten it or explicitly configure a compatible version table."
    )


def test_phase1_downgrade_does_not_delete_platform_only_refresh_sessions():
    source = MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_source = source.split("def downgrade() -> None:", 1)[1]
    normalized = " ".join(downgrade_source.lower().split())

    assert "delete from auth_refresh_sessions" not in normalized, (
        "Downgrade must not silently delete platform-only refresh sessions. "
        "It should refuse to downgrade while membership_id IS NULL rows exist."
    )
    assert "membership_id is null" in normalized, (
        "Downgrade must explicitly check whether platform-only sessions remain."
    )
