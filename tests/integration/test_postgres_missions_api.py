"""Live PostgreSQL regression tests for mission creation and audit persistence.

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

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

ENDPOINT = "/api/v1/missions/orbit-propagation"
_TABLES = (
    "artifact_records",
    "audit_events",
    "provenance_records",
    "verification_findings",
    "orbital_samples",
    "orbital_element_records",
    "workflow_runs",
    "mission_inputs",
    "missions",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> Iterator[AppContainer]:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

    assert _PG_URL is not None
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)
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


def test_postgres_orbit_propagation_persists_mission_linked_audit_events(
    pg_client: TestClient,
    pg_container: AppContainer,
    iss_request: dict[str, object],
) -> None:
    response = pg_client.post(ENDPOINT, json=iss_request)

    assert response.status_code == 201, response.text
    body = response.json()
    mission_id = body["mission_id"]
    assert body["status"] == "completed"

    reloaded = pg_client.get(f"/api/v1/missions/{mission_id}")
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["mission_id"] == mission_id

    response_actions = [event["action"] for event in body["audit"]]
    required = {
        "mission.submitted",
        "mission.validated",
        "workflow.started",
        "mission.completed",
    }
    assert required.issubset(response_actions)

    with pg_container.database.engine.connect() as conn:
        db_actions = (
            conn.execute(
                text("SELECT action FROM audit_events WHERE mission_id = :mission_id ORDER BY at"),
                {"mission_id": mission_id},
            )
            .scalars()
            .all()
        )

    assert db_actions
    assert required.issubset(set(db_actions))
