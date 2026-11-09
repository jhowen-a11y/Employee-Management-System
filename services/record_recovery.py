"""Selective recovery target validation. This module performs no database writes.

The staging setting is independent of the application's SQLAlchemy bind. Never
pass an active database URL to the existing full-restore destination helpers.
"""

import os
import re
import uuid

from flask import current_app
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from services.database_backups import BackupError


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
STAGING_NAME = re.compile(r"^ems_recovery_[0-9a-f]{32}$")


def staging_maintenance_url():
    """Return an explicitly configured loopback maintenance connection.

    No fallback to DATABASE_URL, environment-based libpq routing, DNS names,
    connection query overrides, or application SQLAlchemy engine is allowed.
    Validation deliberately occurs when recovery is requested, so an absent
    staging setting does not interrupt existing EMS features.
    """
    configured = current_app.config.get("RECOVERY_STAGING_DATABASE_URL")
    if not configured:
        raise BackupError("Local recovery staging is not configured.")
    try:
        url = make_url(configured)
        active = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
        port = url.port if url.port is not None else 5432
        if (
            url.drivername != "postgresql+psycopg"
            or url.host not in LOCAL_HOSTS
            or url.database != "postgres"
            or not url.username
            or url.query
            or any(os.environ.get(key) for key in (
                "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"
            ))
            or not 1 <= port <= 65535
        ):
            raise ValueError("unsafe staging configuration")
        # Reject the entire active local server, including aliases and databases
        # with different names. A staging name alone is not isolation.
        if active.host in LOCAL_HOSTS and (active.port or 5432) == port:
            raise ValueError("active server overlaps staging")
    except (ArgumentError, TypeError, ValueError, KeyError):
        raise BackupError("Recovery requires a separate local PostgreSQL staging server.") from None
    return url.set(host="127.0.0.1" if url.host == "localhost" else url.host, port=port)


def new_staging_database_name():
    """Generate a disposable name; generation does not establish ownership."""
    return "ems_recovery_" + uuid.uuid4().hex


def staging_target_url(database_name):
    """Validate a generated target. This does not authorize creation or cleanup.

    Future lifecycle code must record successful creation before marking a
    database owned, and require that ownership record before any drop operation.
    """
    maintenance = staging_maintenance_url()
    if not isinstance(database_name, str) or not STAGING_NAME.fullmatch(database_name):
        raise BackupError("Invalid recovery staging database name.")
    active = make_url(current_app.config["SQLALCHEMY_DATABASE_URI"])
    if database_name.casefold() == (active.database or "").casefold():
        raise BackupError("The active database cannot be a recovery staging target.")
    return maintenance.set(database=database_name)
