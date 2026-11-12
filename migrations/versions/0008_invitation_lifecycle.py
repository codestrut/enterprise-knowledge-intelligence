"""Complete the organisation invitation lifecycle.

Adds invitation purpose, revocation, supersession and acceptance records, plus the
database invariants that make single-use and one-open-invitation rules enforceable,
and links the initial-administrator invitation to tenant onboarding.

PostgreSQL only (partial unique indexes and composite foreign keys). The upgrade
stops, instead of rewriting data, when existing rows would violate the new
invariants. The downgrade refuses to discard lifecycle data once it exists: apply a
forward fix instead.

Service rules this schema relies on (enforced in application code and covered by
tests; not expressible as database constraints):

* Issuing or resending an invitation runs in one transaction. First close any open
  invitation for the same organisation and recipient: UPDATE it with reason
  'superseded' and superseded_by_id set to the new invitation id when it is still
  live, or reason 'expired' (no pointer) when it is already past expires_at. Then
  INSERT the new row with that id. The one-open-invitation index forces this order,
  so the superseded_by foreign key is DEFERRABLE INITIALLY DEFERRED and is
  validated at commit.
* Acceptance is a compare-and-set update guarded by accepted_at IS NULL AND
  revoked_at IS NULL AND expires_at > now(), under a row lock.
* Expiry is time based and is deliberately not part of any index predicate. An open
  but expired invitation still occupies the recipient slot until it is revoked.
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_invitation_lifecycle"
down_revision = "0007_tenant_admin"
branch_labels = None
depends_on = None

_OPEN = "accepted_at IS NULL AND revoked_at IS NULL"

_INVITATION_CHECKS = (
    ("ck_invitations_purpose_valid", "purpose IN ('initial_admin', 'member')"),
    (
        "ck_invitations_initial_admin_role",
        "purpose <> 'initial_admin' OR role = 'organisation_administrator'",
    ),
    (
        "ck_invitations_not_accepted_and_revoked",
        "NOT (accepted_at IS NOT NULL AND revoked_at IS NOT NULL)",
    ),
    (
        "ck_invitations_acceptance_complete",
        "(accepted_at IS NULL) = (accepted_by_user_id IS NULL)",
    ),
    (
        "ck_invitations_revocation_complete",
        "(revoked_at IS NULL) = (revocation_reason IS NULL)",
    ),
    (
        "ck_invitations_revocation_reason_valid",
        "revocation_reason IS NULL OR revocation_reason IN "
        "('superseded', 'revoked_by_admin', 'tenant_suspended', 'tenant_rejected', 'expired')",
    ),
    (
        "ck_invitations_revoker_requires_revocation",
        "revoked_by_user_id IS NULL OR revoked_at IS NOT NULL",
    ),
    (
        "ck_invitations_supersession_pair",
        "(superseded_by_id IS NULL AND (revocation_reason IS NULL OR revocation_reason <> 'superseded')) "
        "OR (superseded_by_id IS NOT NULL AND revocation_reason = 'superseded' AND superseded_by_id <> id)",
    ),
)

# (name, columns, unique, partial predicate)
_INVITATION_INDEXES = (
    (
        "uq_org_invitations_one_open_per_recipient",
        ["organisation_id", "recipient_email"],
        True,
        _OPEN,
    ),
    (
        "uq_org_invitations_one_current_initial_admin",
        ["organisation_id"],
        True,
        "purpose = 'initial_admin' AND revoked_at IS NULL",
    ),
    (
        "ix_org_invitations_recipient_created",
        ["organisation_id", "recipient_email", "created_at"],
        False,
        None,
    ),
    ("ix_org_invitations_open_expiry", ["expires_at"], False, _OPEN),
)


def upgrade() -> None:
    # Recover only history that the 0007 schema can prove. An accepted
    # invitation identifies its accepting user only when that user has a
    # membership in the same organisation and the user's normalized email is
    # the invitation recipient. Do not guess when that relationship is absent.
    #
    # A legacy invitation is an initial-admin invitation only when the
    # onboarding row explicitly records that its initial administrator was
    # accepted AND exactly one accepted administrator invitation matches that
    # organisation and initial-admin email. Email + role alone is not enough.
    #
    # Multiple historical accepted invitations for the same recipient are
    # valid. Only duplicate still-pending invitations would collide with the
    # new one-open-invitation index.
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (
            SELECT 1
            FROM organisation_invitations AS invitation
            WHERE invitation.accepted_at IS NOT NULL
              AND (
                SELECT count(*)
                FROM organisation_memberships AS membership
                JOIN users AS user_record ON user_record.id = membership.user_id
                WHERE membership.organisation_id = invitation.organisation_id
                  AND user_record.email = invitation.recipient_email
              ) <> 1
        ) THEN
            RAISE EXCEPTION 'Resolve accepted organisation_invitations rows without exactly one same-organisation membership matching the recipient email before 0008_invitation_lifecycle';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM organisation_invitations
            WHERE accepted_at IS NULL
            GROUP BY organisation_id, recipient_email
            HAVING count(*) > 1
        ) THEN
            RAISE EXCEPTION 'Resolve multiple pending invitations per organisation and recipient before 0008_invitation_lifecycle';
        END IF;

        IF EXISTS (
            SELECT 1
            FROM tenant_onboarding AS onboarding
            WHERE onboarding.initial_admin_invitation_accepted_at IS NOT NULL
              AND (
                SELECT count(*)
                FROM organisation_invitations AS invitation
                WHERE invitation.organisation_id = onboarding.organisation_id
                  AND invitation.recipient_email = lower(trim(onboarding.initial_admin_email))
                  AND invitation.role = 'organisation_administrator'
                  AND invitation.accepted_at IS NOT NULL
              ) <> 1
        ) THEN
            RAISE EXCEPTION 'Resolve tenant_onboarding accepted initial-administrator records without exactly one matching accepted administrator invitation before 0008_invitation_lifecycle';
        END IF;
        END $$;"""
    )

    op.add_column(
        "organisation_invitations",
        sa.Column("purpose", sa.String(length=24), server_default="member", nullable=False),
    )
    op.add_column(
        "organisation_invitations",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "organisation_invitations",
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "organisation_invitations",
        sa.Column("revocation_reason", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "organisation_invitations",
        sa.Column("superseded_by_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "organisation_invitations",
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
    )

    # The preflight above guarantees one same-organisation membership for every
    # accepted invitation, so this update preserves the historical acceptor
    # without relying on invitation email/role alone.
    op.execute(
        """UPDATE organisation_invitations AS invitation
        SET accepted_by_user_id = user_record.id
        FROM organisation_memberships AS membership
        JOIN users AS user_record ON user_record.id = membership.user_id
        WHERE invitation.accepted_at IS NOT NULL
          AND membership.organisation_id = invitation.organisation_id
          AND user_record.email = invitation.recipient_email"""
    )

    for name, condition in _INVITATION_CHECKS:
        op.create_check_constraint(name, "organisation_invitations", condition)

    # A (organisation_id, id) key lets other tables reference an invitation together
    # with its organisation, so a cross-tenant reference cannot be represented.
    op.create_unique_constraint(
        "uq_organisation_invitations_org_id",
        "organisation_invitations",
        ["organisation_id", "id"],
    )
    op.create_foreign_key(
        "fk_invitations_revoked_by_user",
        "organisation_invitations",
        "users",
        ["revoked_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_invitations_accepted_by_user",
        "organisation_invitations",
        "users",
        ["accepted_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_invitations_superseded_same_org",
        "organisation_invitations",
        "organisation_invitations",
        ["organisation_id", "superseded_by_id"],
        ["organisation_id", "id"],
        ondelete="RESTRICT",
        deferrable=True,
        initially="DEFERRED",
    )

    for name, columns, unique, predicate in _INVITATION_INDEXES:
        if predicate is None:
            op.create_index(name, "organisation_invitations", columns, unique=unique)
        else:
            op.create_index(
                name,
                "organisation_invitations",
                columns,
                unique=unique,
                postgresql_where=sa.text(predicate),
            )

    op.add_column(
        "tenant_onboarding",
        sa.Column("initial_admin_invitation_id", sa.Uuid(), nullable=True),
    )

    # Only an explicit legacy onboarding acceptance timestamp authorizes this
    # purpose backfill. Pending onboarding records intentionally remain NULL
    # and can receive a new initial-admin invitation through the issuance flow.
    op.execute(
        """UPDATE organisation_invitations AS invitation
        SET purpose = 'initial_admin'
        FROM tenant_onboarding AS onboarding
        WHERE onboarding.initial_admin_invitation_accepted_at IS NOT NULL
          AND invitation.organisation_id = onboarding.organisation_id
          AND invitation.recipient_email = lower(trim(onboarding.initial_admin_email))
          AND invitation.role = 'organisation_administrator'
          AND invitation.accepted_at IS NOT NULL"""
    )
    op.execute(
        """UPDATE tenant_onboarding AS onboarding
        SET initial_admin_invitation_id = invitation.id
        FROM organisation_invitations AS invitation
        WHERE onboarding.initial_admin_invitation_accepted_at IS NOT NULL
          AND invitation.organisation_id = onboarding.organisation_id
          AND invitation.recipient_email = lower(trim(onboarding.initial_admin_email))
          AND invitation.role = 'organisation_administrator'
          AND invitation.accepted_at IS NOT NULL"""
    )

    op.create_foreign_key(
        "fk_tenant_onboarding_initial_invitation_same_org",
        "tenant_onboarding",
        "organisation_invitations",
        ["organisation_id", "initial_admin_invitation_id"],
        ["organisation_id", "id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_tenant_onboarding_initial_invitation",
        "tenant_onboarding",
        ["initial_admin_invitation_id"],
    )
    op.create_check_constraint(
        "ck_tenant_onboarding_acceptance_needs_invitation",
        "tenant_onboarding",
        "initial_admin_invitation_accepted_at IS NULL OR initial_admin_invitation_id IS NOT NULL",
    )


def downgrade() -> None:
    # Do not discard lifecycle history. Once it exists, prefer a forward fix.
    op.execute(
        """DO $$ BEGIN
        IF EXISTS (
            SELECT 1 FROM organisation_invitations
            WHERE purpose <> 'member' OR revoked_at IS NOT NULL OR accepted_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'organisation_invitations lifecycle data exists; apply a forward fix instead of downgrading 0008_invitation_lifecycle';
        END IF;
        IF EXISTS (
            SELECT 1 FROM tenant_onboarding WHERE initial_admin_invitation_id IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'tenant_onboarding references invitations; apply a forward fix instead of downgrading 0008_invitation_lifecycle';
        END IF;
        END $$;"""
    )

    op.drop_constraint(
        "ck_tenant_onboarding_acceptance_needs_invitation",
        "tenant_onboarding",
        type_="check",
    )
    op.drop_constraint(
        "uq_tenant_onboarding_initial_invitation", "tenant_onboarding", type_="unique"
    )
    op.drop_constraint(
        "fk_tenant_onboarding_initial_invitation_same_org",
        "tenant_onboarding",
        type_="foreignkey",
    )
    op.drop_column("tenant_onboarding", "initial_admin_invitation_id")

    for name, _columns, _unique, _predicate in reversed(_INVITATION_INDEXES):
        op.drop_index(name, table_name="organisation_invitations")

    op.drop_constraint(
        "fk_invitations_superseded_same_org", "organisation_invitations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_invitations_accepted_by_user", "organisation_invitations", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_invitations_revoked_by_user", "organisation_invitations", type_="foreignkey"
    )
    op.drop_constraint(
        "uq_organisation_invitations_org_id", "organisation_invitations", type_="unique"
    )

    for name, _condition in reversed(_INVITATION_CHECKS):
        op.drop_constraint(name, "organisation_invitations", type_="check")

    for column in (
        "accepted_by_user_id",
        "superseded_by_id",
        "revocation_reason",
        "revoked_by_user_id",
        "revoked_at",
        "purpose",
    ):
        op.drop_column("organisation_invitations", column)
