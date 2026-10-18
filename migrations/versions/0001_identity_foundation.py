"""Create the isolated identity and organisation foundation."""

from alembic import op
import sqlalchemy as sa


revision = "0001_identity_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organisations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(name)) > 0", name="ck_organisations_name_nonempty"),
        sa.CheckConstraint("slug = lower(trim(slug))", name="ck_organisations_slug_normalized"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organisations_slug"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email = lower(trim(email))", name="ck_users_email_normalized"),
        sa.CheckConstraint("length(email) > 0", name="ck_users_email_nonempty"),
        sa.CheckConstraint("password_hash LIKE '$argon2id$%'", name="ck_users_password_hash_argon2id"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_table(
        "organisation_memberships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("organisation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "organisation_administrator",
                "contributor",
                "reader",
                "platform_administrator",
                name="organisation_membership_role",
                native_enum=False,
                create_constraint=True,
                length=40,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organisation_id", "user_id", name="uq_membership_organisation_user"),
    )
    op.create_index("ix_organisation_memberships_organisation_id", "organisation_memberships", ["organisation_id"])
    op.create_index("ix_organisation_memberships_user_id", "organisation_memberships", ["user_id"])
    op.create_index("ix_membership_user_organisation", "organisation_memberships", ["user_id", "organisation_id"])


def downgrade() -> None:
    op.drop_index("ix_membership_user_organisation", table_name="organisation_memberships")
    op.drop_index("ix_organisation_memberships_user_id", table_name="organisation_memberships")
    op.drop_index("ix_organisation_memberships_organisation_id", table_name="organisation_memberships")
    op.drop_table("organisation_memberships")
    op.drop_table("users")
    op.drop_table("organisations")
