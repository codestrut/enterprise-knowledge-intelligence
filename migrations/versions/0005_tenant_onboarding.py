"""Persist platform-led tenant onboarding and provisioning state."""

from alembic import op
import sqlalchemy as sa

revision = "0005_tenant_onboarding"
down_revision = "0004_scoped_security_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_onboarding",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="registration_pending", nullable=False),
        sa.Column("initial_admin_email", sa.String(length=320), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("provisioning_attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provisioning_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provisioning_error_code", sa.String(length=100), nullable=True),
        sa.Column("initial_admin_invitation_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('registration_pending', 'provisioning', 'provisioning_failed', 'pending_admin', 'active', 'suspended', 'rejected')",
            name="ck_tenant_onboarding_status",
        ),
        sa.CheckConstraint("length(trim(initial_admin_email)) > 0", name="ck_tenant_onboarding_admin_email_nonempty"),
        sa.CheckConstraint("provisioning_attempts >= 0", name="ck_tenant_onboarding_attempts_nonnegative"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", name="uq_tenant_onboarding_organisation"),
        sa.UniqueConstraint("created_by_user_id", "idempotency_key", name="uq_tenant_onboarding_creator_idempotency"),
    )
    op.create_index("ix_tenant_onboarding_status_created", "tenant_onboarding", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_tenant_onboarding_status_created", table_name="tenant_onboarding")
    op.drop_table("tenant_onboarding")
