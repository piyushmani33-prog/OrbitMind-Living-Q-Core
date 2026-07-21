"""Stopped-database regressions for content-idempotent source synchronization."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import event

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.persistence.database import Database
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.policies import SourceCatalog
from orbitmind.sources.registry import SourceRegistry

ALEMBIC_HEAD = "a1f4c7e9b230"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _settings(root: Path, database_file: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{database_file.as_posix()}",
        artifacts_dir=root / "artifacts",
        cache_dir=root / "cache",
        env="test",
        network_enabled=False,
    )


def _migrate_to_head(database_file: Path) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_file.as_posix()}")
    command.upgrade(config, "head")


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _assert_released(database_file: Path) -> None:
    moved = database_file.with_suffix(".release-check")
    database_file.replace(moved)
    moved.replace(database_file)


def _assert_no_sidecars(database_file: Path) -> None:
    for suffix in ("-journal", "-wal", "-shm"):
        assert not Path(f"{database_file}{suffix}").exists()


def _database_state(database_file: Path) -> dict[str, object]:
    connection = sqlite3.connect(f"file:{database_file.as_posix()}?mode=ro", uri=True)
    try:
        definitions = connection.execute(
            "SELECT source_id, name, kind, description, enabled, updated_at "
            "FROM source_definitions ORDER BY source_id"
        ).fetchall()
        policies = connection.execute(
            "SELECT source_id, policy_version, base_url, schema_format, schema_version, "
            "network_enabled, snapshot, recorded_at FROM source_policies ORDER BY source_id"
        ).fetchall()
        return {
            "definitions": definitions,
            "policies": policies,
            "revision": connection.execute("SELECT version_num FROM alembic_version").fetchone()[0],
            "integrity": connection.execute("PRAGMA integrity_check").fetchone()[0],
        }
    finally:
        connection.close()


@contextmanager
def _observe_source_writes(database: Database) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith(("insert ", "update ", "delete ")) and any(
            table in normalized for table in ("source_definitions", "source_policies")
        ):
            statements.append(normalized)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(database.engine, "before_cursor_execute", record)


def _catalog_form() -> dict[str, str]:
    return {
        "source_mode": "catalog",
        "catalog_sample_id": "iss",
        "custom_label": "",
        "tle_line1": "",
        "tle_line2": "",
        "observer_latitude_deg": "0",
        "observer_longitude_deg": "0",
        "observer_altitude_metres": "0",
        "start_time_utc": "2019-12-09T19:40:00Z",
        "duration_hours": "1",
        "minimum_elevation_deg": "0",
    }


def test_repository_sync_preserves_exact_stopped_database_bytes(tmp_path: Path) -> None:
    database_file = tmp_path / "repository" / "orbitmind.db"
    database_file.parent.mkdir()
    _migrate_to_head(database_file)
    settings = _settings(tmp_path / "repository", database_file)
    definitions = SourceCatalog(settings).list()
    assert len(definitions) == 5

    database = Database(settings.database_url)
    with database.session() as session:
        repository = SqlAlchemySourceRepository(session)
        for definition in definitions:
            repository.sync_definition(definition)
        session.commit()
    database.dispose()
    _assert_released(database_file)
    _assert_no_sidecars(database_file)
    baseline_state = _database_state(database_file)
    baseline_size = database_file.stat().st_size
    baseline_sha256 = _sha256(database_file)

    database = Database(settings.database_url)
    with _observe_source_writes(database) as statements, database.session() as session:
        repository = SqlAlchemySourceRepository(session)
        for definition in definitions:
            repository.sync_definition(definition)
        assert not session.new
        assert not session.dirty
        assert not session.deleted
        session.commit()
    database.dispose()
    _assert_released(database_file)
    _assert_no_sidecars(database_file)

    assert statements == []
    assert _database_state(database_file) == baseline_state
    assert database_file.stat().st_size == baseline_size
    assert _sha256(database_file) == baseline_sha256


def test_app_container_restart_preserves_exact_stopped_database_bytes(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runtime_root = tmp_path / "runtime"
    database_file = runtime_root / "data" / "orbitmind.db"
    database_file.parent.mkdir(parents=True)
    _migrate_to_head(database_file)
    settings = _settings(runtime_root, database_file)
    assert not settings.network_enabled

    first = AppContainer(settings=settings)
    with TestClient(create_app(first)) as client:
        assert client.get("/health").status_code == 200
        smoke = client.post("/workbench/run", data=_catalog_form())
        assert smoke.status_code == 200
        assert "Next predicted pass/contact window" in smoke.text
    _assert_released(database_file)
    _assert_no_sidecars(database_file)
    baseline_state = _database_state(database_file)
    baseline_size = database_file.stat().st_size
    baseline_sha256 = _sha256(database_file)

    restarted = AppContainer(settings=settings)
    with (
        _observe_source_writes(restarted.database) as statements,
        TestClient(create_app(restarted)) as client,
    ):
        assert client.get("/health").status_code == 200
    _assert_released(database_file)
    _assert_no_sidecars(database_file)
    final_state = _database_state(database_file)

    assert statements == []
    assert len(baseline_state["definitions"]) == len(final_state["definitions"]) == 5
    assert len(baseline_state["policies"]) == len(final_state["policies"]) == 5
    assert final_state == baseline_state
    assert final_state["revision"] == ALEMBIC_HEAD
    assert final_state["integrity"] == "ok"
    assert database_file.stat().st_size == baseline_size
    assert _sha256(database_file) == baseline_sha256
    line1, line2 = SourceRegistry().get_tle("ISS")
    assert line1 not in caplog.text
    assert line2 not in caplog.text
