"""Alembic migration environment for OrbitMind.

The database URL comes from application settings (``ORBITMIND_DATABASE_URL``), so a
single source of truth drives both the app and migrations. ``render_as_batch`` is
enabled for SQLite ALTER support.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

import orbitmind.persistence.models  # noqa: F401 - register all ORM tables
from orbitmind.core.config import get_settings
from orbitmind.persistence.database import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # Prefer an explicitly configured URL (e.g., set by tests) over settings, so
    # migrations are independent of the cached application settings.
    configured = config.get_main_option("sqlalchemy.url")
    return configured or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
