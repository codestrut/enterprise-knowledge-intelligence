"""Add organisation scope to security audit events."""

from alembic import op
import sqlalchemy as sa


revision = "0004_scoped_security_audit"
down_revision = "0003_auth_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_audit_events",
        sa.Column("organisation_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_auth_audit_events_organisation_id",
        "auth_audit_events",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_auth_audit_events_organisation_time",
        "auth_audit_events",
        ["organisation_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_auth_audit_events_organisation_time",
        table_name="auth_audit_events",
    )
    op.drop_constraint(
        "fk_auth_audit_events_organisation_id",
        "auth_audit_events",
        type_="foreignkey",
    )
    op.drop_column("auth_audit_events", "organisation_id")
