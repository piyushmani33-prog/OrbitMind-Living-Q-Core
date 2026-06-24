"""HTTP API tests for bounded observation planning."""

from __future__ import annotations

import builtins
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.observation_planning_schemas import OBSERVATION_PLANNING_DISCLAIMER
from orbitmind.observation_planning import (
    ObservationPlanningRequest,
    PlanningResultStatus,
    translate_request_to_problem,
)
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    SolverConfiguration,
    SolverKind,
)
from orbitmind.optimization.solvers.base import build_result
from orbitmind.persistence.observation_planning_models import (
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
)

BASE = "/api/v1/observation-planning"


def _owner_client(container: AppContainer, owner_id: str) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app)


def _horizon() -> dict[str, str]:
    return {
        "start": "2026-06-21T09:00:00Z",
        "end": "2026-06-21T12:00:00Z",
    }


def _opportunity(
    oid: str = "OPP-A",
    *,
    start: str = "2026-06-21T10:00:00Z",
    end: str = "2026-06-21T10:30:00Z",
    value: float = 5.0,
) -> dict[str, object]:
    return {
        "id": oid,
        "satellite_id": "SAT-A",
        "target_id": "T1",
        "start": start,
        "end": end,
        "mission_value": value,
        "energy_cost": 1.0,
        "storage_cost": 1.0,
    }


def _declared_payload(
    *,
    name: str = "api declared observation planning",
    idempotency_key: str | None = None,
    opportunities: list[dict[str, object]] | None = None,
    constraints: dict[str, object] | None = None,
    limits: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "horizon": _horizon(),
        "source_mode": "declared",
        "fixture_name": None,
        "opportunities": opportunities or [_opportunity()],
        "satellites": [{"id": "SAT-A", "energy_capacity": 20.0, "storage_capacity": 20.0}],
        "targets": [{"id": "T1", "name": "Target 1", "priority": 1}],
    }
    if constraints is not None:
        payload["constraints"] = constraints
    if limits is not None:
        payload["limits"] = limits
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return payload


def _fixture_payload(
    *, name: str = "api fixture observation planning", idempotency_key: str | None = None
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "horizon": _horizon(),
        "source_mode": "fixture",
        "fixture_name": "default",
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return payload


def _greedy_payload() -> dict[str, object]:
    return _declared_payload(
        name="api greedy observation planning",
        opportunities=[
            _opportunity("OPP-A", start="2026-06-21T09:30:00Z", end="2026-06-21T10:00:00Z"),
            _opportunity(
                "OPP-B",
                start="2026-06-21T10:10:00Z",
                end="2026-06-21T10:40:00Z",
                value=6.0,
            ),
        ],
        limits={"max_variables": 2, "exact_max_variables": 1, "max_timeout_seconds": 30.0},
    )


def _infeasible_payload() -> dict[str, object]:
    return _declared_payload(
        name="api infeasible observation planning",
        opportunities=[
            _opportunity("OPP-A", start="2026-06-21T10:00:00Z", end="2026-06-21T10:30:00Z"),
            _opportunity("OPP-B", start="2026-06-21T10:10:00Z", end="2026-06-21T10:40:00Z"),
        ],
        constraints={"mandatory": ["OPP-A", "OPP-B"]},
    )


def _invalid_reference_payload(*, idempotency_key: str | None = "api-invalid") -> dict[str, object]:
    payload = _declared_payload(idempotency_key=idempotency_key)
    opportunity = dict(payload["opportunities"][0])  # type: ignore[index]
    opportunity["satellite_id"] = "SAT-MISSING"
    payload["opportunities"] = [opportunity]
    return payload


def _non_success_planner(status: ExperimentStatus):
    def fake(request: ObservationPlanningRequest) -> object:
        translation = translate_request_to_problem(request)
        config = SolverConfiguration(solver_kind=SolverKind.EXACT)
        solver_result = build_result(
            solver_kind=SolverKind.EXACT,
            solver_name="fake-exact",
            solver_version="test",
            problem_checksum=translation.problem.checksum,
            config=config,
            evaluation=None,
            status=status,
            optimality=OptimalityStatus.UNKNOWN,
            known_optimum=None,
            runtime_seconds=0.0,
            evaluated_candidates=0,
            limitations=status.value,
        )
        from orbitmind.observation_planning import (
            AuthoritativePlanningSolver,
            ObservationPlanningResult,
            PlanningOptimalityLabel,
        )

        return ObservationPlanningResult(
            request_checksum=translation.request_checksum,
            problem_checksum=translation.problem.checksum,
            source_mode=request.source_mode,
            selected_solver=AuthoritativePlanningSolver.EXACT,
            solver_execution_status=status,
            status=PlanningResultStatus.TIMED_OUT
            if status == ExperimentStatus.TIMED_OUT
            else PlanningResultStatus.UNSUPPORTED,
            optimality_label=PlanningOptimalityLabel.UNKNOWN,
            limitations=(status.value,),
            authoritative_result=solver_result,
        )

    return fake


def test_execute_fixture_and_declared_requests(client: TestClient) -> None:
    fixture = client.post(f"{BASE}/executions", json=_fixture_payload())
    declared = client.post(f"{BASE}/executions", json=_declared_payload())

    assert fixture.status_code == 201
    assert declared.status_code == 201
    assert fixture.json()["source_mode"] == "fixture"
    assert declared.json()["source_mode"] == "declared"
    assert declared.json()["final_status"] == "verified-feasible"
    assert OBSERVATION_PLANNING_DISCLAIMER in declared.json()["disclaimer"]


def test_execute_exact_greedy_and_non_success_responses(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    exact = client.post(f"{BASE}/executions", json=_declared_payload())
    greedy = client.post(f"{BASE}/executions", json=_greedy_payload())
    infeasible = client.post(f"{BASE}/executions", json=_infeasible_payload())

    assert exact.json()["selected_solver"] == "exact"
    assert exact.json()["optimality_label"] == "optimal"
    assert greedy.json()["selected_solver"] == "greedy"
    assert greedy.json()["optimality_label"] == "heuristic"
    assert infeasible.status_code == 201
    assert infeasible.json()["final_status"] == "infeasible"
    assert infeasible.json()["plan_id"] is None

    monkeypatch.setattr(
        "orbitmind.observation_planning.orchestration.plan_observation_request",
        _non_success_planner(ExperimentStatus.TIMED_OUT),
    )
    timed_out = client.post(f"{BASE}/executions", json=_declared_payload(name="api timeout"))
    assert timed_out.status_code == 201
    assert timed_out.json()["final_status"] == "timed-out"
    assert timed_out.json()["plan_id"] is None

    monkeypatch.setattr(
        "orbitmind.observation_planning.orchestration.plan_observation_request",
        _non_success_planner(ExperimentStatus.UNSUPPORTED),
    )
    unsupported = client.post(f"{BASE}/executions", json=_declared_payload(name="api unsupported"))
    assert unsupported.status_code == 201
    assert unsupported.json()["final_status"] == "unsupported"
    assert unsupported.json()["plan_id"] is None


def test_invalid_translation_returns_422_and_no_persisted_graph(client: TestClient) -> None:
    response = client.post(f"{BASE}/executions", json=_invalid_reference_payload())

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    listing = client.get(f"{BASE}/requests").json()
    assert listing["total"] == 0


def test_owner_is_local_principal_and_spoofed_owner_is_rejected(
    container: AppContainer,
) -> None:
    with _owner_client(container, "owner-a") as owner_a:
        spoofed = _declared_payload(idempotency_key="owner-spoof")
        spoofed["owner_id"] = "owner-b"
        assert owner_a.post(f"{BASE}/executions", json=spoofed).status_code == 422

        created = owner_a.post(
            f"{BASE}/executions", json=_declared_payload(idempotency_key="owner-a")
        ).json()

    with _owner_client(container, "owner-b") as owner_b:
        assert owner_b.get(f"{BASE}/requests/{created['request_id']}").status_code == 404


def test_idempotency_reuse_conflict_and_different_owners(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _owner_client(container, "owner-a") as owner_a:
        first = owner_a.post(
            f"{BASE}/executions", json=_declared_payload(idempotency_key="same-key")
        )
        second = owner_a.post(
            f"{BASE}/executions", json=_declared_payload(idempotency_key="same-key")
        )
        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["request_id"] == first.json()["request_id"]
        assert second.json()["run_id"] == first.json()["run_id"]
        assert second.json()["request_created"] is False
        assert second.json()["run_created"] is False

        def forbidden_planner(_: ObservationPlanningRequest) -> object:
            raise AssertionError("solver should not run for an idempotency conflict")

        monkeypatch.setattr(
            "orbitmind.observation_planning.orchestration.plan_observation_request",
            forbidden_planner,
        )
        different = _declared_payload(name="different", idempotency_key="same-key")
        conflict = owner_a.post(f"{BASE}/executions", json=different)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_conflict"

    monkeypatch.undo()

    with _owner_client(container, "owner-b") as owner_b:
        independent = owner_b.post(
            f"{BASE}/executions",
            json=_declared_payload(name="owner-b", idempotency_key="same-key"),
        )
        assert independent.status_code == 201
        assert independent.json()["request_id"] != first.json()["request_id"]


def test_retrieve_and_list_request_run_and_plan(client: TestClient) -> None:
    created = client.post(f"{BASE}/executions", json=_declared_payload()).json()

    request = client.get(f"{BASE}/requests/{created['request_id']}")
    execution = client.get(f"{BASE}/runs/{created['run_id']}")
    plan = client.get(f"{BASE}/plans/{created['plan_id']}")
    request_runs = client.get(f"{BASE}/requests/{created['request_id']}/runs")
    plan_list = client.get(f"{BASE}/plans")

    assert request.status_code == 200
    assert "idempotency_key" not in request.json()["request"]
    assert execution.status_code == 200
    assert execution.json()["plan"]["id"] == created["plan_id"]
    assert plan.status_code == 200
    assert plan.json()["id"] == created["plan_id"]
    assert request_runs.json()["items"][0]["id"] == created["run_id"]
    assert plan_list.json()["items"][0]["id"] == created["plan_id"]


def test_lists_filter_and_paginate_strictly(client: TestClient) -> None:
    first = client.post(
        f"{BASE}/executions",
        json=_declared_payload(name="first", idempotency_key="first"),
    ).json()
    second = client.post(
        f"{BASE}/executions",
        json=_fixture_payload(name="second", idempotency_key="second"),
    ).json()

    page = client.get(f"{BASE}/requests?limit=1&offset=0")
    repeat = client.get(f"{BASE}/requests?limit=1&offset=0")
    next_page = client.get(f"{BASE}/requests?limit=1&offset=1")
    fixture_only = client.get(f"{BASE}/requests?source_mode=fixture")
    runs = client.get(
        f"{BASE}/requests/{first['request_id']}/runs"
        "?status=verified-feasible&source_mode=declared&authoritative_solver=exact&feasible_only=true"
    )
    plans = client.get(f"{BASE}/plans?source_mode=fixture")

    assert page.status_code == 200
    assert page.json() == repeat.json()
    assert page.json()["items"][0]["id"] != next_page.json()["items"][0]["id"]
    assert fixture_only.json()["items"][0]["id"] == second["request_id"]
    assert runs.json()["items"][0]["id"] == first["run_id"]
    assert plans.json()["items"][0]["id"] == second["plan_id"]

    for query in ("limit=true", "limit=1.0", "limit=-1", "limit=", "limit= 1", "offset=-1"):
        assert client.get(f"{BASE}/requests?{query}").status_code == 422


def test_created_time_filters_reject_naive_and_invalid_range(client: TestClient) -> None:
    client.post(f"{BASE}/executions", json=_declared_payload())

    ok = client.get(
        f"{BASE}/requests?created-from=2026-01-01T00:00:00Z&created-to=2999-01-01T00:00:00Z"
    )
    naive = client.get(f"{BASE}/requests?created-from=2026-01-01T00:00:00")
    invalid = client.get(
        f"{BASE}/requests?created-from=2026-01-02T00:00:00Z&created-to=2026-01-01T00:00:00Z"
    )

    assert ok.status_code == 200
    assert ok.json()["total"] >= 1
    assert naive.status_code == 422
    assert invalid.status_code == 422


def test_tamper_and_schema_version_errors_are_bounded(
    client: TestClient, container: AppContainer
) -> None:
    created = client.post(f"{BASE}/executions", json=_declared_payload()).json()
    with container.database.session() as session:
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

    request = client.get(f"{BASE}/requests/{created['request_id']}")
    assert request.status_code == 422
    assert request.json() == {
        "code": "validation_error",
        "message": "observation-planning request checksum mismatch",
    }

    created_2 = client.post(
        f"{BASE}/executions", json=_declared_payload(name="schema", idempotency_key="schema")
    ).json()
    with container.database.session() as session:
        session.execute(
            update(ObservationPlanningRunRow)
            .where(ObservationPlanningRunRow.id == created_2["run_id"])
            .values(result_schema_version="future")
        )
        session.commit()

    run = client.get(f"{BASE}/runs/{created_2['run_id']}")
    assert run.status_code == 422
    assert "schema version" in run.json()["message"]


def test_openapi_includes_observation_planning_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{BASE}/executions" in paths
    assert f"{BASE}/requests/{{request_id}}" in paths
    assert f"{BASE}/runs/{{run_id}}" in paths
    assert f"{BASE}/plans/{{plan_id}}" in paths


def test_observation_planning_api_uses_no_quantum_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.startswith("orbitmind.quantum") or name.startswith(
            "orbitmind.optimization.quantum"
        ):
            raise AssertionError(f"quantum import attempted: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    response = client.post(
        f"{BASE}/executions", json=_declared_payload(name="no quantum", idempotency_key="no-q")
    )

    assert response.status_code == 201
