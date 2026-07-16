"""SQLite compatibility preflight for the packaged runtime."""

from __future__ import annotations

import gc
import sqlite3
import sys
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from alembic import command
from alembic.config import Config

from orbitmind.runtime.paths import RuntimePaths
from orbitmind.runtime.status import ExitCode, ReasonCode, RuntimeFailure

ALEMBIC_HEAD: Final = "n9c0d1e2f3g4"
SQLITE_BUSY_TIMEOUT_MS: Final = 5_000


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


def _known_revisions(resources: MigrationResources) -> tuple[str, ...]:
    revisions: list[str] = []
    for path in sorted((resources.migrations_dir / "versions").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if line.startswith("revision: str = "):
                revisions.append(line.partition("=")[2].strip().strip('"'))
                break
    return tuple(revisions)


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


def _upgrade(config: Config) -> None:
    """Run Alembic and promptly collect its completed context on Windows."""

    try:
        command.upgrade(config, ALEMBIC_HEAD)
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
    config = _alembic_config(database_url, migration_resources)
    existed = paths.database_file.exists()
    if not existed:
        try:
            _upgrade(config)
        except Exception as exc:
            paths.database_file.unlink(missing_ok=True)
            raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE) from exc
        del config
        gc.collect()
        if _inspect_database(paths.database_file) != ALEMBIC_HEAD:
            raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
        return None

    revision = _inspect_database(paths.database_file)
    if revision == ALEMBIC_HEAD:
        return None
    known = _known_revisions(migration_resources)
    if revision not in known or ALEMBIC_HEAD not in known:
        raise RuntimeFailure(ExitCode.DATABASE_CORRUPTION, ReasonCode.DATABASE_CORRUPTION)
    if confirm_migration is None or not confirm_migration(revision):
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)
    backup = _backup_database(paths.database_file, paths.backups_dir, now())
    try:
        _upgrade(config)
        del config
        gc.collect()
        if _inspect_database(paths.database_file) != ALEMBIC_HEAD:
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
