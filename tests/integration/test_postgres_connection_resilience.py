"""Live PostgreSQL checks for honest pooled-connection resilience."""

from __future__ import annotations

import os
from contextlib import suppress

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import NullPool

from orbitmind.persistence.database import Database

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]


def _terminate_backend(url: str, backend_pid: int) -> None:
    killer = create_engine(url, poolclass=NullPool)
    try:
        with killer.begin() as connection:
            terminated = connection.scalar(
                text("SELECT pg_terminate_backend(:backend_pid)"),
                {"backend_pid": backend_pid},
            )
        assert terminated is True
    finally:
        killer.dispose()


def _admin_url(url: str) -> URL:
    parsed = make_url(url)
    if parsed.database == "postgres":
        pytest.skip("connection-restoration test requires a disposable non-postgres database")
    return parsed.set(database="postgres")


def _set_connections_allowed(url: str, *, allowed: bool) -> None:
    parsed = make_url(url)
    database_name = parsed.database
    assert database_name is not None
    quoted_name = '"' + database_name.replace('"', '""') + '"'
    admin = create_engine(
        _admin_url(url),
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin.connect() as connection:
            connection.execute(
                text(
                    f"ALTER DATABASE {quoted_name} WITH ALLOW_CONNECTIONS "
                    + ("true" if allowed else "false")
                )
            )
    finally:
        admin.dispose()


def test_stale_idle_connection_is_replaced_at_checkout() -> None:
    assert _PG_URL is not None
    database = Database(_PG_URL)
    try:
        with database.engine.connect() as connection:
            backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)

        _terminate_backend(_PG_URL, backend_pid)

        with database.engine.connect() as replacement:
            replacement_pid = replacement.scalar(text("SELECT pg_backend_pid()"))
            assert replacement.scalar(text("SELECT 1")) == 1
        assert isinstance(replacement_pid, int)
        assert replacement_pid != backend_pid
    finally:
        database.dispose()


def test_in_flight_transaction_loss_raises_without_replay() -> None:
    assert _PG_URL is not None
    database = Database(_PG_URL)
    connection = database.engine.connect()
    transaction = connection.begin()
    try:
        backend_pid = connection.scalar(text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        connection.execute(text("SELECT 1"))
        _terminate_backend(_PG_URL, backend_pid)

        with pytest.raises(DBAPIError):
            connection.execute(text("SELECT 2"))
    finally:
        with suppress(Exception):
            transaction.rollback()
        with suppress(Exception):
            connection.close()
        database.dispose()


def test_database_unavailable_at_first_check_then_restored() -> None:
    assert _PG_URL is not None
    database = Database(_PG_URL)
    _set_connections_allowed(_PG_URL, allowed=False)
    try:
        assert database.check_connection() is False
    finally:
        _set_connections_allowed(_PG_URL, allowed=True)
    try:
        assert database.check_connection() is True
    finally:
        database.dispose()
