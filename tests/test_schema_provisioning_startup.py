"""Regression tests for startup schema provisioning boundaries."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.persistence.database import Database

_TEST_SIGNING_KEY = "test-evidence-signing-key-0123456789abcdef"


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'schema-startup.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key=_TEST_SIGNING_KEY,
    )


def _source_definition_count(container: AppContainer) -> int:
    with container.database.engine.connect() as conn:
        return int(conn.execute(text("SELECT count(*) FROM source_definitions")).scalar_one())


def _force_postgres_dialect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Database, "is_postgres", property(lambda _self: True))


def test_sqlite_init_storage_bootstraps_schema_and_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original_create_all: Callable[[Database], None] = Database.create_all

    def create_all_spy(database: Database) -> None:
        nonlocal calls
        calls += 1
        original_create_all(database)

    monkeypatch.setattr(Database, "create_all", create_all_spy)

    container = AppContainer(settings=_settings(tmp_path))
    container.init_storage()

    assert calls == 1
    assert _source_definition_count(container) > 0


def test_postgres_init_storage_skips_create_all_but_syncs_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = AppContainer(settings=_settings(tmp_path))
    # Simulates an Alembic-created schema without needing a live PostgreSQL service.
    container.database.create_all()
    _force_postgres_dialect(monkeypatch)

    def fail_create_all(_database: Database) -> None:
        raise AssertionError("PostgreSQL init_storage must not call create_all")

    monkeypatch.setattr(Database, "create_all", fail_create_all)

    container.init_storage()

    assert _source_definition_count(container) > 0


def test_postgres_app_startup_skips_create_all_but_keeps_catalog_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = AppContainer(settings=_settings(tmp_path))
    # Simulates an Alembic-created schema before PostgreSQL-backed app startup.
    container.database.create_all()
    _force_postgres_dialect(monkeypatch)

    def fail_create_all(_database: Database) -> None:
        raise AssertionError("PostgreSQL app startup must not call create_all")

    monkeypatch.setattr(Database, "create_all", fail_create_all)

    with TestClient(create_app(container)) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert _source_definition_count(container) > 0
