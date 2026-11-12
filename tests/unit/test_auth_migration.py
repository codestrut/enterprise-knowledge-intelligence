from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


ROOT = Path(__file__).resolve().parents[2]


def test_auth_migrations_are_a_linear_versioned_chain():
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_heads() == ["0008_invitation_lifecycle"]
    expected = [
        ("0008_invitation_lifecycle", "0007_tenant_admin"),
        ("0007_tenant_admin", "0006_platform_roles_and_recovery"),
        ("0006_platform_roles_and_recovery", "0005_tenant_onboarding"),
        ("0005_tenant_onboarding", "0004_scoped_security_audit"),
        ("0004_scoped_security_audit", "0003_auth_hardening"),
        ("0003_auth_hardening", "0002_auth_refresh_sessions"),
        ("0002_auth_refresh_sessions", "0001_identity_foundation"),
        ("0001_identity_foundation", None),
    ]
    for revision_id, parent_id in expected:
        assert scripts.get_revision(revision_id).down_revision == parent_id


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


def test_tenant_onboarding_migration_is_additive_and_does_not_touch_document_storage():
    migration = (ROOT / "migrations/versions/0005_tenant_onboarding.py").read_text()
    assert '"tenant_onboarding"' in migration
    assert '"idempotency_key"' in migration
    assert '"request_fingerprint"' in migration
    assert '"initial_admin_email"' in migration
    assert '"provisioning_error_code"' in migration
    assert "documents_manifest" not in migration
    assert "uploads" not in migration
    assert "def downgrade()" in migration


def test_invitation_lifecycle_migration_preserves_only_provable_legacy_history():
    migration = (ROOT / "migrations/versions/0008_invitation_lifecycle.py").read_text()

    # Accepted actors are recovered through a same-organisation membership
    # whose user's normalized email matches the historical recipient.
    assert "organisation_memberships AS membership" in migration
    assert "user_record.email = invitation.recipient_email" in migration
    assert "SET accepted_by_user_id = user_record.id" in migration

    # Legacy role/email alone must not convert an invitation to initial_admin.
    assert "SET purpose = 'initial_admin'" in migration
    assert "onboarding.initial_admin_invitation_accepted_at IS NOT NULL" in migration
    assert "initial_admin_invitation_id = invitation.id" in migration

    # Historical accepted invitations may repeat; only multiple pending rows
    # collide with the new one-open-invitation-per-recipient invariant.
    assert "WHERE accepted_at IS NULL\n            GROUP BY organisation_id, recipient_email" in migration
    assert "GROUP BY organisation_id, recipient_email HAVING count(*) > 1" not in migration
