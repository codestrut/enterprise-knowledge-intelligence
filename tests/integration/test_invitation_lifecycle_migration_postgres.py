"""Populated-0007 to 0008 invitation lifecycle migration regression.

This test deliberately rewinds only a fresh, empty disposable PostgreSQL test
DB to 0007, seeds representative legacy rows, and upgrades it to head. The
runner invokes this file before the lifecycle/concurrency suites.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


_RAW_URL = os.environ.get("EKIP_TEST_DATABASE_URL")
if not _RAW_URL:
    pytest.skip("EKIP_TEST_DATABASE_URL is not configured", allow_module_level=True)

_URL = make_url(_RAW_URL)
if _URL.drivername != "postgresql+psycopg":
    pytest.skip("EKIP_TEST_DATABASE_URL must use postgresql+psycopg", allow_module_level=True)
if _URL.host not in {"127.0.0.1", "localhost", "::1"}:
    pytest.skip("Migration regression requires a loopback PostgreSQL host", allow_module_level=True)
if not _URL.database or "test" not in _URL.database.lower():
    pytest.skip("PostgreSQL database name must contain 'test'", allow_module_level=True)


ROOT = Path(__file__).resolve().parents[2]


def test_populated_0007_database_backfills_only_provable_invitation_history():
    engine = create_engine(_URL, pool_pre_ping=True)
    previous_database_url = os.environ.get("EKIP_DATABASE_URL")
    os.environ["EKIP_DATABASE_URL"] = _RAW_URL
    try:
        with engine.connect() as connection:
            actual_database = connection.scalar(text("SELECT current_database()"))
            assert actual_database == _URL.database
            assert "alembic_version" in inspect(connection).get_table_names()
            current_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
            assert current_revision == "0008_invitation_lifecycle"

            # This test intentionally rewinds the disposable DB. Refuse to run
            # if any earlier test or user data has been left in it.
            for table in (
                "organisation_invitations",
                "tenant_onboarding",
                "organisation_memberships",
                "users",
                "organisations",
            ):
                assert connection.scalar(text(f'SELECT count(*) FROM "{table}"')) == 0, (
                    f"Refusing to rewind non-empty test table: {table}"
                )

        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "migrations"))
        command.downgrade(config, "0007_tenant_admin")

        org_accepted, org_pending = uuid4(), uuid4()
        user_initial, user_member, user_inviter = uuid4(), uuid4(), uuid4()
        membership_initial, membership_member = uuid4(), uuid4()
        onboarding_accepted, onboarding_pending = uuid4(), uuid4()
        invite_initial, invite_member_old_a, invite_member_old_b, invite_pending_admin = (
            uuid4(), uuid4(), uuid4(), uuid4()
        )
        now = datetime.now(UTC).replace(microsecond=0)
        accepted_at = now - timedelta(minutes=2)
        expires_at = now + timedelta(days=5)

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO organisations (id, name, slug) VALUES "
                    "(:id_a, 'Legacy accepted tenant', :slug_a), "
                    "(:id_b, 'Legacy pending tenant', :slug_b)"
                ),
                {"id_a": org_accepted, "id_b": org_pending,
                 "slug_a": f"legacy-accepted-{org_accepted.hex}",
                 "slug_b": f"legacy-pending-{org_pending.hex}"},
            )
            connection.execute(
                text(
                    "INSERT INTO users (id, email, password_hash) VALUES "
                    "(:id_initial, 'initial-admin@legacy.example.test', :password), "
                    "(:id_member, 'member@legacy.example.test', :password), "
                    "(:id_inviter, 'inviter@legacy.example.test', :password)"
                ),
                {"id_initial": user_initial, "id_member": user_member,
                 "id_inviter": user_inviter,
                 "password": "$argon2id$v=19$m=65536,t=3,p=4$legacy$fixture"},
            )
            connection.execute(
                text(
                    "INSERT INTO organisation_memberships "
                    "(id, organisation_id, user_id, role, is_active) VALUES "
                    "(:id_initial, :org, :user_initial, 'organisation_administrator', true), "
                    "(:id_member, :org, :user_member, 'contributor', true)"
                ),
                {"id_initial": membership_initial, "id_member": membership_member,
                 "org": org_accepted, "user_initial": user_initial, "user_member": user_member},
            )
            connection.execute(
                text(
                    "INSERT INTO tenant_onboarding "
                    "(id, organisation_id, status, initial_admin_email, idempotency_key, "
                    "request_fingerprint, created_by_user_id, provisioning_attempts, "
                    "initial_admin_invitation_accepted_at) VALUES "
                    "(:accepted_id, :accepted_org, 'active', 'initial-admin@legacy.example.test', "
                    "'legacy-accepted', :fingerprint, :creator, 1, :accepted_at), "
                    "(:pending_id, :pending_org, 'pending_admin', 'pending-admin@legacy.example.test', "
                    "'legacy-pending', :fingerprint, :creator, 1, NULL)"
                ),
                {"accepted_id": onboarding_accepted, "accepted_org": org_accepted,
                 "pending_id": onboarding_pending, "pending_org": org_pending,
                 "fingerprint": "a" * 64, "creator": user_inviter,
                 "accepted_at": accepted_at},
            )
            connection.execute(
                text(
                    "INSERT INTO organisation_invitations "
                    "(id, organisation_id, recipient_email, role, token_hash, invited_by_user_id, "
                    "expires_at, accepted_at) VALUES "
                    "(:id_initial, :org_accepted, 'initial-admin@legacy.example.test', "
                    "'organisation_administrator', :token_initial, :inviter, :expires, :accepted_at), "
                    "(:id_member_a, :org_accepted, 'member@legacy.example.test', 'contributor', "
                    ":token_member_a, :inviter, :expires, :member_accepted_a), "
                    "(:id_member_b, :org_accepted, 'member@legacy.example.test', 'contributor', "
                    ":token_member_b, :inviter, :expires, :member_accepted_b), "
                    "(:id_pending, :org_pending, 'pending-admin@legacy.example.test', "
                    "'organisation_administrator', :token_pending, :inviter, :expires, NULL)"
                ),
                {"id_initial": invite_initial, "id_member_a": invite_member_old_a,
                 "id_member_b": invite_member_old_b, "id_pending": invite_pending_admin,
                 "org_accepted": org_accepted, "org_pending": org_pending,
                 "token_initial": "1" * 64, "token_member_a": "2" * 64,
                 "token_member_b": "3" * 64, "token_pending": "4" * 64,
                 "inviter": user_inviter, "expires": expires_at,
                 "accepted_at": accepted_at,
                 "member_accepted_a": accepted_at - timedelta(days=1),
                 "member_accepted_b": accepted_at - timedelta(hours=1)},
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            rows = {
                row.id: row
                for row in connection.execute(
                    text(
                        "SELECT id, purpose, accepted_at, accepted_by_user_id "
                        "FROM organisation_invitations WHERE id IN "
                        "(:initial, :member_a, :member_b, :pending)"
                    ),
                    {"initial": invite_initial, "member_a": invite_member_old_a,
                     "member_b": invite_member_old_b, "pending": invite_pending_admin},
                )
            }
            assert rows[invite_initial].purpose == "initial_admin"
            assert rows[invite_initial].accepted_by_user_id == user_initial
            assert rows[invite_member_old_a].purpose == "member"
            assert rows[invite_member_old_a].accepted_by_user_id == user_member
            assert rows[invite_member_old_b].purpose == "member"
            assert rows[invite_member_old_b].accepted_by_user_id == user_member
            assert rows[invite_pending_admin].purpose == "member"
            assert rows[invite_pending_admin].accepted_by_user_id is None

            onboarding_rows = {
                row.id: row
                for row in connection.execute(
                    text(
                        "SELECT id, initial_admin_invitation_id "
                        "FROM tenant_onboarding WHERE id IN (:accepted, :pending)"
                    ),
                    {"accepted": onboarding_accepted, "pending": onboarding_pending},
                )
            }
            assert onboarding_rows[onboarding_accepted].initial_admin_invitation_id == invite_initial
            assert onboarding_rows[onboarding_pending].initial_admin_invitation_id is None
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008_invitation_lifecycle"
    finally:
        engine.dispose()
        if previous_database_url is None:
            os.environ.pop("EKIP_DATABASE_URL", None)
        else:
            os.environ["EKIP_DATABASE_URL"] = previous_database_url
