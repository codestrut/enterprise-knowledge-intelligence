"""Explicit environment-based PostgreSQL configuration for auth storage.

Importing this module never creates an engine or opens a database connection.
"""

import os
from collections.abc import Mapping

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


DATABASE_URL_ENV = "EKIP_DATABASE_URL"


def database_url_from_environment(
    environ: Mapping[str, str] | None = None,
) -> URL:
    """Parse a PostgreSQL URL from configuration without connecting to it."""
    environment = os.environ if environ is None else environ
    value = environment.get(DATABASE_URL_ENV)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{DATABASE_URL_ENV} must be configured explicitly.")

    try:
        url = make_url(value.strip())
    except ArgumentError:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} is not a valid SQLAlchemy URL."
        ) from None

    if url.drivername != "postgresql+psycopg":
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must use the postgresql+psycopg driver."
        )
    if not url.host or not url.database:
        raise RuntimeError(
            f"{DATABASE_URL_ENV} must include a PostgreSQL host and database."
        )
    return url
