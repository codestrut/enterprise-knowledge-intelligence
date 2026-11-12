"""Add organisation invitations, organisation settings, and nullable membership in refresh sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0007_tenant_admin"
down_revision = "0006_platform_roles_and_recovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Organisation Invitations
    op.create_table(
        "organisation_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("recipient_email", sa.String(length=320), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(recipient_email)) > 0", name="ck_invitations_recipient_nonempty"),
        sa.CheckConstraint("recipient_email = lower(trim(recipient_email))", name="ck_invitations_recipient_normalized"),
        sa.CheckConstraint("role IN ('organisation_administrator', 'contributor', 'reader')", name="ck_invitations_role_valid"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_organisation_invitations_token_hash"),
    )
    op.create_index("ix_organisation_invitations_org", "organisation_invitations", ["organisation_id"])
    op.create_index("ix_organisation_invitations_email", "organisation_invitations", ["recipient_email"])

    # 2. Organisation Settings
    op.create_table(
        "organisation_settings",
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("allowed_email_domains", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("session_idle_timeout_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("session_idle_timeout_minutes >= 5 AND session_idle_timeout_minutes <= 1440", name="ck_settings_timeout_range"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("organisation_id"),
    )

    # 3. Allow nullable membership_id in auth_refresh_sessions for independent platform admin sessions
    op.alter_column("auth_refresh_sessions", "membership_id", nullable=True)


def downgrade() -> None:
    # Never delete platform-only refresh sessions implicitly. An operator must
    # revoke/expire and explicitly remove those records before downgrading.
    bind = op.get_bind()
    platform_session_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM auth_refresh_sessions WHERE membership_id IS NULL")
    ).scalar_one()
    if platform_session_count:
        raise RuntimeError(
            "Cannot downgrade 0007_tenant_admin while platform-only refresh sessions exist. "
            "Revoke and explicitly purge those sessions before retrying."
        )
    op.alter_column("auth_refresh_sessions", "membership_id", nullable=False)

    op.drop_table("organisation_settings")
    op.drop_index("ix_organisation_invitations_email", table_name="organisation_invitations")
    op.drop_index("ix_organisation_invitations_org", table_name="organisation_invitations")
    op.drop_table("organisation_invitations")
