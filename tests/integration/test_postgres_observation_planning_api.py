"""Live PostgreSQL API tests for bounded observation planning."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text, update

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.core.config import Settings
from orbitmind.persistence.observation_planning_models import ObservationPlanningRequestRow

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

BASE = "/api/v1/observation-planning"
_TABLES = (
    "observation_plans",
    "observation_planning_runs",
    "observation_planning_requests",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> AppContainer:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

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


def _client(container: AppContainer, owner_id: str = "local-owner") -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app)


def _exec(container: AppContainer, sql: str) -> list:
    with container.database.engine.connect() as conn:
        return list(conn.execute(text(sql)))


def _horizon() -> dict[str, str]:
    return {"start": "2026-06-21T09:00:00Z", "end": "2026-06-21T12:00:00Z"}


def _opportunity(oid: str = "OPP-A", *, start_min: int = 60, end_min: int = 90) -> dict:
    return {
        "id": oid,
        "satellite_id": "SAT-A",
        "target_id": "T1",
        "start": f"2026-06-21T{9 + start_min // 60:02d}:{start_min % 60:02d}:00Z",
        "end": f"2026-06-21T{9 + end_min // 60:02d}:{end_min % 60:02d}:00Z",
        "mission_value": 5.0,
        "energy_cost": 1.0,
        "storage_cost": 1.0,
    }


def _payload(
    *,
    name: str = "postgres api declared",
    idempotency_key: str | None = None,
    constraints: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "horizon": _horizon(),
        "source_mode": "declared",
        "fixture_name": None,
        "opportunities": [_opportunity()],
        "satellites": [{"id": "SAT-A", "energy_capacity": 20.0, "storage_capacity": 20.0}],
        "targets": [{"id": "T1"}],
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    if constraints is not None:
        payload["constraints"] = constraints
    return payload


def _infeasible_payload() -> dict[str, object]:
    payload = _payload(name="postgres api infeasible", idempotency_key="pg-api-infeasible")
    payload["opportunities"] = [
        _opportunity("OPP-A", start_min=60, end_min=90),
        _opportunity("OPP-B", start_min=70, end_min=100),
    ]
    payload["constraints"] = {"mandatory": ["OPP-A", "OPP-B"]}
    return payload


def _invalid_payload() -> dict[str, object]:
    payload = _payload(name="postgres api invalid", idempotency_key="pg-api-invalid")
    opportunity = dict(payload["opportunities"][0])  # type: ignore[index]
    opportunity["satellite_id"] = "SAT-MISSING"
    payload["opportunities"] = [opportunity]
    return payload


def test_postgres_api_executes_and_retrieves_plan(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        created = client.post(f"{BASE}/executions", json=_payload(idempotency_key="pg-api-ok"))
        assert created.status_code == 201
        body = created.json()

        assert client.get(f"{BASE}/requests/{body['request_id']}").status_code == 200
        run = client.get(f"{BASE}/runs/{body['run_id']}")
        plan = client.get(f"{BASE}/plans/{body['plan_id']}")

    assert run.status_code == 200
    assert run.json()["plan"]["id"] == body["plan_id"]
    assert plan.status_code == 200
    assert plan.json()["id"] == body["plan_id"]


def test_postgres_api_idempotent_replay_conflict_and_owner_isolation(
    pg_container: AppContainer,
) -> None:
    with _client(pg_container, "owner-a") as owner_a:
        first = owner_a.post(
            f"{BASE}/executions", json=_payload(idempotency_key="pg-api-key")
        ).json()
        second = owner_a.post(f"{BASE}/executions", json=_payload(idempotency_key="pg-api-key"))
        conflict = owner_a.post(
            f"{BASE}/executions",
            json=_payload(name="different", idempotency_key="pg-api-key"),
        )

    with _client(pg_container, "owner-b") as owner_b:
        hidden = owner_b.get(f"{BASE}/requests/{first['request_id']}")
        independent = owner_b.post(
            f"{BASE}/executions",
            json=_payload(name="owner b", idempotency_key="pg-api-key"),
        )

    assert second.status_code == 200
    assert second.json()["run_id"] == first["run_id"]
    assert conflict.status_code == 409
    assert hidden.status_code == 404
    assert independent.status_code == 201
    assert independent.json()["request_id"] != first["request_id"]


def test_postgres_api_lists_filter_and_paginate(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        first = client.post(
            f"{BASE}/executions", json=_payload(name="first", idempotency_key="pg-api-first")
        ).json()
        second = client.post(
            f"{BASE}/executions", json=_payload(name="second", idempotency_key="pg-api-second")
        ).json()
        page = client.get(f"{BASE}/requests?limit=1&offset=0")
        next_page = client.get(f"{BASE}/requests?limit=1&offset=1")
        runs = client.get(
            f"{BASE}/requests/{first['request_id']}/runs"
            "?status=verified-feasible&source_mode=declared&authoritative_solver=exact"
        )
        plans = client.get(
            f"{BASE}/plans?created-from=2026-01-01T00:00:00Z&created-to=2999-01-01T00:00:00Z"
        )

    assert page.status_code == 200
    assert page.json()["has_next"] is True
    assert page.json()["items"][0]["id"] != next_page.json()["items"][0]["id"]
    assert runs.status_code == 200
    assert runs.json()["items"][0]["request_id"] == first["request_id"]
    assert plans.status_code == 200
    assert {item["id"] for item in plans.json()["items"]} == {first["plan_id"], second["plan_id"]}


def test_postgres_api_non_success_run_without_plan(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        created = client.post(f"{BASE}/executions", json=_infeasible_payload())
        run = client.get(f"{BASE}/runs/{created.json()['run_id']}")

    assert created.status_code == 201
    assert created.json()["final_status"] == "infeasible"
    assert created.json()["plan_id"] is None
    assert run.status_code == 200
    assert run.json()["plan"] is None


def test_postgres_api_tamper_detection_maps_to_safe_error(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        created = client.post(
            f"{BASE}/executions", json=_payload(idempotency_key="pg-api-tamper")
        ).json()

    with pg_container.database.session() as session:
        row = session.get(ObservationPlanningRequestRow, created["request_id"])
        assert row is not None
        tampered = dict(row.request_json)
        tampered["name"] = "tampered"
        session.execute(
            update(ObservationPlanningRequestRow)
            .where(ObservationPlanningRequestRow.id == created["request_id"])
            .values(request_json=tampered)
        )
        session.commit()

    with _client(pg_container) as client:
        response = client.get(f"{BASE}/requests/{created['request_id']}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "checksum" in response.json()["message"]


def test_postgres_api_invalid_execution_rolls_back(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        response = client.post(f"{BASE}/executions", json=_invalid_payload())

    assert response.status_code == 422
    assert _exec(pg_container, "SELECT count(*) FROM observation_planning_requests")[0][0] == 0
    assert _exec(pg_container, "SELECT count(*) FROM observation_planning_runs")[0][0] == 0
    assert _exec(pg_container, "SELECT count(*) FROM observation_plans")[0][0] == 0
