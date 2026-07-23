"""SQLite compatibility preflight for the packaged runtime."""

from __future__ import annotations

import gc
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from orbitmind.runtime.paths import RuntimePaths
from orbitmind.runtime.status import ExitCode, ReasonCode, RuntimeFailure

SQLITE_BUSY_TIMEOUT_MS: Final = 5_000


class SchemaState(StrEnum):
    """Relationship between a database revision and the packaged migration graph."""

    CURRENT = "current"
    MIGRATION_REQUIRED = "migration_required"
    UNRECOGNISED = "unrecognised"
    GRAPH_INVALID = "graph_invalid"


@dataclass(frozen=True)
class MigrationResources:
    alembic_ini: Path
    migrations_dir: Path

    @classmethod
    def discover(cls) -> MigrationResources:
        if getattr(sys, "frozen", False):
            root = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        else:
            root = Path(__file__).resolve().parents[3]
        return cls(root / "alembic.ini", root / "migrations")


def _alembic_config(database_url: str, resources: MigrationResources) -> Config:
    if not resources.alembic_ini.is_file() or not resources.migrations_dir.is_dir():
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
    config = Config(str(resources.alembic_ini))
    config.set_main_option("script_location", str(resources.migrations_dir))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def packaged_script(resources: MigrationResources) -> ScriptDirectory:
    """Load the packaged Alembic graph without parsing migration source text."""

    if not resources.alembic_ini.is_file() or not resources.migrations_dir.is_dir():
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
    config = Config(str(resources.alembic_ini))
    config.set_main_option("script_location", str(resources.migrations_dir))
    return ScriptDirectory.from_config(config)


def packaged_head(script: ScriptDirectory) -> str:
    """Return the sole packaged head, failing closed for an invalid graph."""

    heads = script.get_heads()
    if len(heads) != 1:
        raise RuntimeFailure(
            ExitCode.MIGRATION_GRAPH_INVALID,
            ReasonCode.MIGRATION_GRAPH_INVALID,
        )
    return heads[0]


def classify_revision(revision: str, script: ScriptDirectory) -> SchemaState:
    """Classify a database revision against the authoritative Alembic graph."""

    heads = script.get_heads()
    if len(heads) != 1:
        return SchemaState.GRAPH_INVALID
    head = heads[0]
    if revision == head:
        return SchemaState.CURRENT
    if any(item.revision == revision for item in script.iterate_revisions(head, "base")):
        return SchemaState.MIGRATION_REQUIRED
    return SchemaState.UNRECOGNISED


def _inspect_database(path: Path) -> str:
    try:
        with closing(sqlite3.connect(path, timeout=5.0)) as connection:
            connection.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS}")
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() == "wal":
                raise sqlite3.DatabaseError
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)]:
                raise sqlite3.DatabaseError
            revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    except sqlite3.DatabaseError as exc:
        raise RuntimeFailure(ExitCode.DATABASE_CORRUPTION, ReasonCode.DATABASE_CORRUPTION) from exc
    if len(revisions) != 1 or not isinstance(revisions[0][0], str):
        raise RuntimeFailure(ExitCode.DATABASE_CORRUPTION, ReasonCode.DATABASE_CORRUPTION)
    return revisions[0][0]


def _backup_database(path: Path, backup_dir: Path, now: datetime) -> Path:
    timestamp = now.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"orbitmind-{timestamp}-pre-migration.sqlite3"
    if destination.exists():
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
    try:
        with (
            closing(sqlite3.connect(path, timeout=5.0)) as source,
            closing(sqlite3.connect(destination)) as backup,
        ):
            source.backup(backup)
        if destination.stat().st_size <= 0:
            raise OSError
        _inspect_database(destination)
    except (OSError, sqlite3.DatabaseError, RuntimeFailure) as exc:
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE) from exc
    return destination


def _upgrade(config: Config, target_revision: str) -> None:
    """Run Alembic and promptly collect its completed context on Windows."""

    try:
        command.upgrade(config, target_revision)
    finally:
        # Alembic's proxy retains its closed migration context in a cycle. CPython
        # eventually collects it, but Windows otherwise keeps the SQLite handle long
        # enough to block backup/temp-root cleanup.
        gc.collect()


def _preflight_sqlite_impl(
    paths: RuntimePaths,
    database_url: str,
    *,
    resources: MigrationResources | None = None,
    confirm_migration: Callable[[str], bool] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Path | None:
    """Create or validate/migrate the one approved SQLite database."""

    expected_url = f"sqlite:///{paths.database_file.as_posix()}"
    if database_url != expected_url:
        raise RuntimeFailure(ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION)
    migration_resources = resources or MigrationResources.discover()
    script = packaged_script(migration_resources)
    head = packaged_head(script)
    config = _alembic_config(database_url, migration_resources)
    existed = paths.database_file.exists()
    if not existed:
        try:
            _upgrade(config, head)
        except Exception as exc:
            paths.database_file.unlink(missing_ok=True)
            raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE) from exc
        del config
        gc.collect()
        if _inspect_database(paths.database_file) != head:
            raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
        return None

    revision = _inspect_database(paths.database_file)
    state = classify_revision(revision, script)
    if state is SchemaState.CURRENT:
        return None
    if state is SchemaState.GRAPH_INVALID:
        raise RuntimeFailure(
            ExitCode.MIGRATION_GRAPH_INVALID,
            ReasonCode.MIGRATION_GRAPH_INVALID,
        )
    if state is SchemaState.UNRECOGNISED:
        raise RuntimeFailure(
            ExitCode.SCHEMA_UNRECOGNISED,
            ReasonCode.SCHEMA_UNRECOGNISED,
        )
    if confirm_migration is None or not confirm_migration(revision):
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
    backup = _backup_database(paths.database_file, paths.backups_dir, now())
    try:
        _upgrade(config, head)
        del config
        gc.collect()
        if _inspect_database(paths.database_file) != head:
            raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
    except Exception as exc:
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE) from exc
    return backup


def preflight_sqlite(
    paths: RuntimePaths,
    database_url: str,
    *,
    resources: MigrationResources | None = None,
    confirm_migration: Callable[[str], bool] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Path | None:
    """Run preflight and release completed Alembic proxy cycles before returning."""

    try:
        return _preflight_sqlite_impl(
            paths,
            database_url,
            resources=resources,
            confirm_migration=confirm_migration,
            now=now,
        )
    finally:
        gc.collect()
