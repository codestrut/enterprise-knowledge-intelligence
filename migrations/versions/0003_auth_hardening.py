"""Add password/session hardening, platform scope, and audit metadata."""

from alembic import op
import sqlalchemy as sa


revision = "0003_auth_hardening"
down_revision = "0002_auth_refresh_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Never silently turn a platform assignment into a tenant role. Stop the
    # migration so an operator can review and explicitly resolve such rows.
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (
            SELECT 1 FROM organisation_memberships
            WHERE role = 'platform_administrator'
        ) THEN
            RAISE EXCEPTION 'Resolve platform_administrator membership rows before 0003_auth_hardening';
        END IF;
        END $$;"""
    )

    op.add_column(
        "users",
        sa.Column("is_platform_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "organisations",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.drop_constraint(
        "organisation_membership_role", "organisation_memberships", type_="check"
    )
    op.create_check_constraint(
        "organisation_membership_role",
        "organisation_memberships",
        "role IN ('organisation_administrator', 'contributor', 'reader')",
    )
    op.create_unique_constraint(
        "uq_membership_id_user", "organisation_memberships", ["id", "user_id"]
    )

    op.add_column(
        "auth_refresh_sessions",
        sa.Column("family_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auth_refresh_sessions",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "auth_refresh_sessions", sa.Column("rotation_key_hash", sa.String(length=64), nullable=True)
    )
    op.execute(
        "UPDATE auth_refresh_sessions SET family_expires_at = expires_at, last_used_at = created_at"
    )
    op.alter_column("auth_refresh_sessions", "family_expires_at", nullable=False)
    op.alter_column("auth_refresh_sessions", "last_used_at", nullable=False)
    op.create_foreign_key(
        "fk_auth_refresh_sessions_membership_user",
        "auth_refresh_sessions",
        "organisation_memberships",
        ["membership_id", "user_id"],
        ["id", "user_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "auth_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=True),
        sa.Column("target_id", sa.String(length=80), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("details", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.CheckConstraint("length(event_type) > 0", name="ck_auth_audit_event_type_nonempty"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_audit_events_actor_time", "auth_audit_events", ["actor_user_id", "occurred_at"]
    )
    op.create_index(
        "ix_auth_audit_events_event_time", "auth_audit_events", ["event_type", "occurred_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_auth_audit_events_event_time", table_name="auth_audit_events")
    op.drop_index("ix_auth_audit_events_actor_time", table_name="auth_audit_events")
    op.drop_table("auth_audit_events")
    op.drop_constraint(
        "fk_auth_refresh_sessions_membership_user",
        "auth_refresh_sessions",
        type_="foreignkey",
    )
    op.drop_column("auth_refresh_sessions", "rotation_key_hash")
    op.drop_column("auth_refresh_sessions", "last_used_at")
    op.drop_column("auth_refresh_sessions", "family_expires_at")
    op.drop_constraint("uq_membership_id_user", "organisation_memberships", type_="unique")
    op.drop_constraint(
        "organisation_membership_role", "organisation_memberships", type_="check"
    )
    op.create_check_constraint(
        "organisation_membership_role",
        "organisation_memberships",
        "role IN ('organisation_administrator', 'contributor', 'reader', 'platform_administrator')",
    )
    op.drop_column("organisations", "is_active")
    op.drop_column("users", "is_platform_admin")
