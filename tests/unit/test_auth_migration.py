from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def test_auth_migrations_are_a_linear_versioned_chain():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()

    assert heads == ["0004_scoped_security_audit"]
    revision = scripts.get_revision(heads[0])
    assert revision.down_revision == "0003_auth_hardening"
    assert scripts.get_revision(revision.down_revision).down_revision == "0002_auth_refresh_sessions"
    assert scripts.get_revision(scripts.get_revision(revision.down_revision).down_revision).down_revision == "0001_identity_foundation"
    assert scripts.get_revision(scripts.get_revision(scripts.get_revision(revision.down_revision).down_revision).down_revision).down_revision is None


def test_initial_migration_only_creates_auth_tables_and_reversible_schema():
    migration = (ROOT / "migrations/versions/0001_identity_foundation.py").read_text()

    assert '"organisations"' in migration
    assert '"users"' in migration
    assert '"organisation_memberships"' in migration
    assert "documents_manifest" not in migration
    assert "uploads" not in migration
    assert "def downgrade()" in migration
    assert "op.drop_table(\"organisations\")" in migration


def test_refresh_session_migration_is_scoped_and_stores_only_token_hashes():
    migration = (
        ROOT / "migrations/versions/0002_auth_refresh_sessions.py"
    ).read_text()

    assert '"auth_refresh_sessions"' in migration
    assert 'sa.Column("token_hash", sa.String(length=64), nullable=False)' in migration
    assert 'sa.Column("membership_id", sa.Uuid(), nullable=False)' in migration
    assert 'sa.Column("family_id", sa.Uuid(), nullable=False)' in migration
    assert 'sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True)' in migration
    assert 'sa.Column("replaced_by_id", sa.Uuid(), nullable=True)' in migration
    assert 'sa.Column("is_active", sa.Boolean()' in migration
    assert "plain_token" not in migration
    assert "documents_manifest" not in migration
    assert "uploads" not in migration


def test_security_migration_separates_platform_scope_and_adds_audit_and_expiry():
    migration = (ROOT / "migrations/versions/0003_auth_hardening.py").read_text()

    assert '"is_platform_admin"' in migration
    assert '"auth_audit_events"' in migration
    assert '"family_expires_at"' in migration
    assert '"last_used_at"' in migration
    assert '"rotation_key_hash"' in migration
    assert "fk_auth_refresh_sessions_membership_user" in migration
    assert "RAISE EXCEPTION 'Resolve platform_administrator membership rows" in migration
    assert "documents_manifest" not in migration
    assert "uploads" not in migration


def test_scoped_audit_migration_adds_organisation_boundary_without_touching_documents():
    migration = (ROOT / "migrations/versions/0004_scoped_security_audit.py").read_text()
    assert 'sa.Column("organisation_id", sa.Uuid(), nullable=True)' in migration
    assert '"organisations"' in migration
    assert '"ix_auth_audit_events_organisation_time"' in migration
    assert "documents_manifest" not in migration
    assert "uploads" not in migration
