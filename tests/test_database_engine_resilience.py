"""Offline contracts for database engine checkout resilience."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine as sqlalchemy_create_engine

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.persistence import database as database_module
from orbitmind.persistence.database import Database


def _capture_driver_free_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Capture PostgreSQL engine options without requiring its optional driver."""
    captured: dict[str, Any] = {}

    def capture_create_engine(url: str, **kwargs: Any) -> Any:
        captured["url"] = url
        captured["kwargs"] = dict(kwargs)
        return sqlalchemy_create_engine("sqlite:///:memory:", **kwargs)

    monkeypatch.setattr(database_module, "create_engine", capture_create_engine)
    return captured


def test_non_sqlite_engine_enables_pre_ping_without_default_recycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_driver_free_engine(monkeypatch)
    database = Database("postgresql+psycopg://unused:unused@127.0.0.1:1/unused")
    try:
        assert captured["kwargs"] == {
            "future": True,
            "connect_args": {},
            "pool_pre_ping": True,
        }
        assert database.engine.pool._pre_ping is True
        assert database.engine.pool._recycle == -1
    finally:
        database.dispose()


def test_sqlite_engine_options_remain_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def capture_create_engine(url: str, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return sqlalchemy_create_engine(url, **kwargs)

    monkeypatch.setattr(database_module, "create_engine", capture_create_engine)
    database = Database(
        f"sqlite:///{(tmp_path / 'resilience.db').as_posix()}",
        recycle_seconds=60,
    )
    try:
        assert captured == {
            "future": True,
            "connect_args": {"check_same_thread": False},
        }
        assert database.engine.pool._pre_ping is False
        assert database.engine.pool._recycle == -1
        assert database.check_connection() is True
    finally:
        database.dispose()


def test_non_sqlite_recycle_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_driver_free_engine(monkeypatch)
    database = Database(
        "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        recycle_seconds=73,
    )
    try:
        assert captured["kwargs"] == {
            "future": True,
            "connect_args": {},
            "pool_pre_ping": True,
            "pool_recycle": 73,
        }
        assert database.engine.pool._pre_ping is True
        assert database.engine.pool._recycle == 73
    finally:
        database.dispose()


def test_recycle_setting_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORBITMIND_DATABASE_POOL_RECYCLE_SECONDS", "91")

    settings = Settings(_env_file=None)

    assert settings.database_pool_recycle_seconds == 91


def test_app_container_threads_recycle_setting_to_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured = _capture_driver_free_engine(monkeypatch)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
        database_pool_recycle_seconds=127,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
    )
    container = AppContainer(settings=settings, caller_owns_lifecycle=True)
    try:
        assert captured["kwargs"] == {
            "future": True,
            "connect_args": {},
            "pool_pre_ping": True,
            "pool_recycle": 127,
        }
        assert container.database.engine.pool._pre_ping is True
        assert container.database.engine.pool._recycle == 127
    finally:
        container.shutdown()
