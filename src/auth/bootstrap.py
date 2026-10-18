"""Explicit, interactive bootstrap CLI for the first platform account."""

from __future__ import annotations

import argparse
from getpass import getpass
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.auth.database import database_url_from_environment
from src.auth.models import AuditEvent, Organisation, OrganisationMembership, User
from src.auth.passwords import PasswordPolicyError, hash_password
from src.auth.permissions import Role


_EXISTING_ORGANISATION_REFUSAL = (
    "Organisation already exists; rerun with --allow-existing-org to add an administrator."
)


def bootstrap_platform_admin(db: Session, email: str, password_hash: str) -> str:
    """Create the initial user-level platform administrator, idempotently."""
    with db.begin():
        existing = db.scalar(select(User).where(User.email == email.strip().lower()))
        if existing is not None:
            if existing.is_active and existing.is_platform_admin:
                return "already_configured"
            raise ValueError("That identity already exists; bootstrap did not change it.")

        user = User(
            email=email,
            password_hash=password_hash,
            is_platform_admin=True,
        )
        db.add(user)
        db.flush()
        db.add(
            AuditEvent(
                actor_user_id=user.id,
                event_type="platform.bootstrap_admin_created",
                target_type="user",
                target_id=str(user.id),
                details={"source": "bootstrap_cli"},
            )
        )
    return "created"


def bootstrap_organisation(
    db: Session,
    *,
    name: str,
    slug: str,
    admin_email: str,
    password_hash: str | None = None,
    allow_existing_org: bool = False,
) -> str:
    """Create an organisation and its first administrator without resetting users.

    Adding an administrator to an organisation that already exists requires the explicit
    ``allow_existing_org`` override (CLI: ``--allow-existing-org``) and a matching name.
    """
    with db.begin():
        organisation = db.scalar(
            select(Organisation).where(Organisation.slug == slug.strip().lower())
        )
        user = db.scalar(
            select(User).where(User.email == admin_email.strip().lower())
        )
        existing_organisation = organisation is not None
        if existing_organisation and organisation.name.strip() != name.strip():
            raise ValueError(
                "Organisation name does not match the existing organisation; "
                "bootstrap did not change it."
            )
        if organisation is not None and user is not None:
            existing = db.scalar(
                select(OrganisationMembership).where(
                    OrganisationMembership.organisation_id == organisation.id,
                    OrganisationMembership.user_id == user.id,
                )
            )
            if existing is not None:
                if existing.is_active and existing.role is Role.ORGANISATION_ADMINISTRATOR:
                    return "already_configured"
                raise ValueError("Existing membership differs; bootstrap did not change it.")
        if existing_organisation and not allow_existing_org:
            raise ValueError(_EXISTING_ORGANISATION_REFUSAL)

        if user is not None and not user.is_active:
            raise ValueError("Inactive identities cannot receive bootstrap membership.")
        if user is None:
            if password_hash is None:
                raise ValueError("A password hash is required for a new identity.")
            user = User(email=admin_email, password_hash=password_hash)
            db.add(user)
            db.flush()
        if organisation is None:
            organisation = Organisation(name=name, slug=slug)
            db.add(organisation)
            db.flush()

        membership = OrganisationMembership(
            organisation=organisation,
            user=user,
            role=Role.ORGANISATION_ADMINISTRATOR,
            is_active=True,
        )
        db.add(membership)
        db.flush()
        details = {"membership_id": str(membership.id), "source": "bootstrap_cli"}
        if existing_organisation:
            details["existing_organisation"] = True
        db.add(
            AuditEvent(
                actor_user_id=user.id,
                organisation_id=organisation.id,
                event_type=(
                    "organisation.bootstrap_admin_added"
                    if existing_organisation
                    else "organisation.bootstrap_created"
                ),
                target_type="organisation",
                target_id=str(organisation.id),
                details=details,
            )
        )
    return "admin_added" if existing_organisation else "created"


def _read_new_password() -> str:
    password = getpass("New password: ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise ValueError("Passwords did not match.")
    return hash_password(password)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m src.auth.bootstrap",
        description="Explicit managed-account bootstrap. There is no public registration.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    platform_parser = subparsers.add_parser("platform-admin")
    platform_parser.add_argument("--email", required=True)
    platform_parser.add_argument("--confirm", action="store_true", required=True)
    organisation_parser = subparsers.add_parser("organisation")
    organisation_parser.add_argument("--name", required=True)
    organisation_parser.add_argument("--slug", required=True)
    organisation_parser.add_argument("--admin-email", required=True)
    organisation_parser.add_argument("--confirm", action="store_true", required=True)
    organisation_parser.add_argument(
        "--allow-existing-org",
        action="store_true",
        help="Explicitly allow adding an administrator to an organisation that already exists.",
    )
    args = parser.parse_args(argv)

    try:
        password_hash = None
        identity_email = args.email if args.command == "platform-admin" else args.admin_email
        probe_engine = create_engine(database_url_from_environment(), pool_pre_ping=True)
        try:
            with Session(probe_engine) as probe:
                known_user = probe.scalar(
                    select(User).where(User.email == identity_email.strip().lower())
                )
                if args.command == "platform-admin":
                    if known_user is not None and not (
                        known_user.is_active and known_user.is_platform_admin
                    ):
                        raise ValueError(
                            "That identity already exists; bootstrap did not change it."
                        )
                elif known_user is not None and not known_user.is_active:
                    raise ValueError("Inactive identities cannot receive bootstrap membership.")
                elif not args.allow_existing_org and probe.scalar(
                    select(Organisation.id).where(Organisation.slug == args.slug.strip().lower())
                ) is not None:
                    # Refuse before prompting for a password; the function re-checks atomically.
                    already_admin = known_user is not None and probe.scalar(
                        select(OrganisationMembership.id)
                        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
                        .where(
                            Organisation.slug == args.slug.strip().lower(),
                            OrganisationMembership.user_id == known_user.id,
                        )
                    ) is not None
                    if not already_admin:
                        raise ValueError(_EXISTING_ORGANISATION_REFUSAL)
        finally:
            probe_engine.dispose()
        if known_user is None:
            password_hash = _read_new_password()

        engine = create_engine(database_url_from_environment(), pool_pre_ping=True)
        try:
            with Session(engine) as db:
                if args.command == "platform-admin":
                    if known_user is not None:
                        result = "already_configured"
                    else:
                        assert password_hash is not None
                        result = bootstrap_platform_admin(db, args.email, password_hash)
                else:
                    if known_user is not None:
                        password_hash = None
                    result = bootstrap_organisation(
                        db,
                        name=args.name,
                        slug=args.slug,
                        admin_email=args.admin_email,
                        password_hash=password_hash,
                        allow_existing_org=args.allow_existing_org,
                    )
        finally:
            engine.dispose()
    except (ValueError, PasswordPolicyError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print("Bootstrap failed; no credential material was displayed.", file=sys.stderr)
        return 2

    print("Bootstrap already configured." if result == "already_configured" else "Bootstrap complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
