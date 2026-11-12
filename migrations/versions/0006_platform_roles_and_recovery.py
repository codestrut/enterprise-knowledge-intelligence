"""Add explicit platform role assignments and provisioning recovery timestamps."""
from alembic import op
import sqlalchemy as sa

revision = "0006_platform_roles_and_recovery"
down_revision = "0005_tenant_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_role_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=48), nullable=False),
        sa.Column("assigned_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("role IN ('platform_super_administrator', 'platform_tenant_creator', 'platform_tenant_approver', 'platform_provisioning_operator')", name="ck_platform_role_assignment_role"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "role", name="uq_platform_role_assignment_user_role"),
    )
    op.create_index("ix_platform_role_assignments_user_id", "platform_role_assignments", ["user_id"])
    op.add_column("tenant_onboarding", sa.Column("provisioning_started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenant_onboarding", "provisioning_started_at")
    op.drop_index("ix_platform_role_assignments_user_id", table_name="platform_role_assignments")
    op.drop_table("platform_role_assignments")
