"""Live PostgreSQL API tests for small-body persistence ordering.

These tests rely on an already Alembic-migrated disposable PostgreSQL database.
They do not call ``create_all()`` so migration defects and PostgreSQL ordering
behavior cannot be hidden by ORM metadata creation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.conftest import load_jpl_fixture, make_jpl_transport
from tests.signing_fixtures import TEST_ONLY_EVIDENCE_SIGNING_MATERIAL

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

ENDPOINT = "/api/v1/small-bodies/close-approaches"
_TABLES = (
    "close_approaches",
    "small_body_query_runs",
    "audit_events",
    "source_cache_entries",
    "source_fetches",
    "source_health_events",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> Iterator[AppContainer]:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

    assert _PG_URL is not None
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        network_enabled=True,
        jpl_sbdb_enabled=True,
        jpl_cad_enabled=True,
        env="test",
        evidence_signing_key=TEST_ONLY_EVIDENCE_SIGNING_MATERIAL,
    )
    transport = make_jpl_transport(cad=load_jpl_fixture("cad_response.json"))
    container = AppContainer(settings, jpl_transport=transport, jpl_sleep=lambda _: None)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield container
    container.database.engine.dispose()


@pytest.fixture
def pg_client(pg_container: AppContainer) -> Iterator[TestClient]:
    with TestClient(create_app(pg_container), raise_server_exceptions=False) as client:
        yield client


def test_postgres_close_approaches_persist_query_run_before_children(
    pg_client: TestClient,
    pg_container: AppContainer,
) -> None:
    response = pg_client.post(
        ENDPOINT,
        json={
            "filter": {
                "date_min": "2026-01-01T00:00:00Z",
                "date_max": "2026-12-01T00:00:00Z",
            }
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"]["returned"] == 3

    with pg_container.database.engine.connect() as conn:
        parent_rows = (
            conn.execute(text("SELECT id, run_type FROM small_body_query_runs ORDER BY created_at"))
            .mappings()
            .all()
        )
        close_rows = (
            conn.execute(
                text("SELECT query_run_id, designation FROM close_approaches ORDER BY time_utc")
            )
            .mappings()
            .all()
        )
        audit_actions = (
            conn.execute(text("SELECT action FROM audit_events ORDER BY at")).scalars().all()
        )

    assert len(parent_rows) == 1
    parent_id = parent_rows[0]["id"]
    assert parent_rows[0]["run_type"] == "cad"
    assert close_rows
    assert {row["query_run_id"] for row in close_rows} == {parent_id}
    assert {row["designation"] for row in close_rows} == {"99942", "2011 AG5", "2023 DW"}
    assert "smallbody.cad_query_requested" in audit_actions
    assert "smallbody.close_approaches_persisted" in audit_actions
