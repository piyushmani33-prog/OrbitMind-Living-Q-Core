"""Integration tests for the bounded optimization API + memory links + Aer guard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.container import AppContainer
from orbitmind.optimization.models import BenchmarkThresholds

pytestmark = pytest.mark.integration


def _create(client: TestClient, fixture: str = "default") -> str:
    resp = client.post("/api/v1/optimization/problems", json={"fixture": fixture})
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_create_list_get_problem(client: TestClient) -> None:
    pid = _create(client)
    listing = client.get("/api/v1/optimization/problems").json()
    assert listing["total"] >= 1
    got = client.get(f"/api/v1/optimization/problems/{pid}").json()
    assert got["id"] == pid and got["checksum"]


def test_create_validation(client: TestClient) -> None:
    assert client.post("/api/v1/optimization/problems", json={"fixture": "nope"}).status_code == 422
    assert client.post("/api/v1/optimization/problems", json={}).status_code == 422


def test_classical_solves(client: TestClient) -> None:
    pid = _create(client)
    exact = client.post(
        f"/api/v1/optimization/problems/{pid}/solve/classical", json={"solver": "exact", "seed": 7}
    ).json()["result"]
    assert exact["optimality_status"] == "optimal" and exact["objective_value"] == 10.0
    greedy = client.post(
        f"/api/v1/optimization/problems/{pid}/solve/classical", json={"solver": "greedy"}
    ).json()["result"]
    assert greedy["feasible"] is True
    bad = client.post(
        f"/api/v1/optimization/problems/{pid}/solve/classical", json={"solver": "annealer"}
    )
    assert bad.status_code == 422


def test_quantum_solve_request_bounds(client: TestClient) -> None:
    pid = _create(client)
    assert (
        client.post(
            f"/api/v1/optimization/problems/{pid}/solve/quantum", json={"shots": 999999}
        ).status_code
        == 422
    )


def test_benchmark_generates_verified_artifacts(client: TestClient) -> None:
    pid = _create(client)
    resp = client.post(
        f"/api/v1/optimization/problems/{pid}/benchmark",
        json={"seed": 7, "shots": 1024, "optimizer_iterations": 16, "generate_artifacts": True},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verified"] is True
    assert "quantum advantage" in body["disclaimer"].lower()
    run = body["run"]
    assert run["comparison"]["conclusion"] in (
        "quantum-competitive",
        "quantum-worse",
        "equivalent-objective",
        "classical-exact-best",
        "insufficient-evidence",
    )
    assert len(run["solver_results"]) == 2
    types = {a["type"] for a in run["artifacts"]}
    assert "selected_observation_timeline" in types and "benchmark_summary_json" in types
    # Artifacts retrievable by run id.
    arts = client.get(f"/api/v1/optimization/runs/{run['id']}/artifacts").json()
    assert len(arts["artifacts"]) >= 5


def test_runs_listing(client: TestClient) -> None:
    pid = _create(client)
    client.post(f"/api/v1/optimization/problems/{pid}/solve/classical", json={"solver": "exact"})
    runs = client.get("/api/v1/optimization/runs").json()
    assert any(r["kind"] == "exact" for r in runs["items"])


def test_quantum_unsupported_when_aer_absent(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("orbitmind.optimization.service.quantum_available", lambda: False)
    monkeypatch.setattr("orbitmind.optimization.benchmark.quantum_available", lambda: False)
    problem = container.optimization_service.create_problem(
        __import__("orbitmind.optimization.fixtures", fromlist=["fixture"]).fixture("default")
    )
    experiment = container.optimization_service.solve_quantum(
        problem.id, seed=1, shots=512, optimizer_iterations=8, qaoa_layers=1, timeout_seconds=5.0
    )
    assert experiment.status.value == "unsupported"
    # Benchmark still runs the classical baselines and concludes without quantum.
    run, _findings = container.optimization_service.benchmark(problem.id, seed=1)
    assert (
        run.quantum_experiment is not None and run.quantum_experiment.status.value == "unsupported"
    )
    assert run.comparison.conclusion.value == "classical-exact-best"


def test_benchmark_registers_bounded_memory_links(container: AppContainer) -> None:
    from orbitmind.optimization import fixtures

    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    edge_kinds = {n.edge_kind.value for n in neighbors.neighbors}
    assert "solved-by" in edge_kinds  # problem -> solved-by -> solver run


_VALID_PROBLEM = {
    "name": "client-problem",
    "opportunities": [
        {
            "id": "OPP-1",
            "satellite_id": "SAT-A",
            "target_id": "T1",
            "start": "2026-06-21T10:00:00Z",
            "end": "2026-06-21T10:30:00Z",
            "mission_value": 5.0,
            "duration_seconds": 1800.0,
            "energy_cost": 2.0,
            "storage_cost": 1.0,
        }
    ],
    "satellites": [{"id": "SAT-A", "energy_capacity": 100.0, "storage_capacity": 100.0}],
    "targets": [{"id": "T1"}],
}


def test_dto_create_server_stamps_fields(client: TestClient) -> None:
    resp = client.post("/api/v1/optimization/problems", json={"problem": _VALID_PROBLEM})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["source"] == "api"  # server-stamped
    assert body["epistemic_status"] == "deterministic-calculation"  # server-stamped
    assert body["checksum"]  # server-stamped
    assert body["opportunities"][0]["provenance"].startswith("client-submitted")


def test_dto_rejects_server_owned_and_custom_penalty(client: TestClient) -> None:
    for field, value in [
        ("epistemic_status", "verified-fact"),
        ("created_at", "2020-01-01T00:00:00Z"),
        ("problem_checksum", "deadbeef"),
        ("checksum", "x"),
        ("id", "client-hijack"),
        ("source", "trusted"),
        ("limits", {"max_variables": 999}),
        ("verification_status", "verified"),
    ]:
        bad = {"problem": {**_VALID_PROBLEM, field: value}}
        assert client.post("/api/v1/optimization/problems", json=bad).status_code == 422, field
    # Custom penalty coefficients are not accepted via the API (finding #6).
    badp = {
        "problem": {
            **_VALID_PROBLEM,
            "objective": {"mission_value_weight": 1.0, "penalty_coefficient": 5.0},
        }
    }
    assert client.post("/api/v1/optimization/problems", json=badp).status_code == 422


def _problem_with_window(start: str, end: str) -> dict:
    opp = {**_VALID_PROBLEM["opportunities"][0], "start": start, "end": end}
    return {"problem": {**_VALID_PROBLEM, "opportunities": [opp]}}


def test_naive_start_timestamp_returns_422(client: TestClient) -> None:
    body = _problem_with_window("2026-06-21T10:00:00", "2026-06-21T10:30:00+00:00")
    resp = client.post("/api/v1/optimization/problems", json=body)
    assert resp.status_code == 422  # not 500
    assert resp.json().get("detail") or resp.json().get("code")  # standard validation envelope


def test_naive_end_timestamp_returns_422(client: TestClient) -> None:
    body = _problem_with_window("2026-06-21T10:00:00+00:00", "2026-06-21T10:30:00")
    assert client.post("/api/v1/optimization/problems", json=body).status_code == 422


def test_both_naive_timestamps_return_422(client: TestClient) -> None:
    body = _problem_with_window("2026-06-21T10:00:00", "2026-06-21T10:30:00")
    resp = client.post("/api/v1/optimization/problems", json=body)
    assert resp.status_code == 422
    assert resp.json() != {"code": "internal_error", "message": "an internal error occurred"}


def test_inverted_window_returns_422(client: TestClient) -> None:
    body = _problem_with_window("2026-06-21T10:30:00+00:00", "2026-06-21T10:00:00+00:00")
    assert client.post("/api/v1/optimization/problems", json=body).status_code == 422


def test_offset_timestamps_normalized_to_utc(client: TestClient) -> None:
    # +05:30 input must be accepted and normalized to UTC (15:30+05:30 == 10:00Z).
    body = _problem_with_window("2026-06-21T15:30:00+05:30", "2026-06-21T16:30:00+05:30")
    resp = client.post("/api/v1/optimization/problems", json=body)
    assert resp.status_code == 200, resp.text
    window = resp.json()["opportunities"][0]["window"]
    assert window["start"].endswith("+00:00") or window["start"].endswith("Z")
    assert window["start"].startswith("2026-06-21T10:00:00")
    assert window["end"].startswith("2026-06-21T11:00:00")


def test_duplicate_problem_creation_is_idempotent(client: TestClient) -> None:
    a = client.post("/api/v1/optimization/problems", json={"fixture": "default"}).json()
    b = client.post("/api/v1/optimization/problems", json={"fixture": "default"}).json()
    assert a["id"] == b["id"] and a["checksum"] == b["checksum"]
    got = client.get(f"/api/v1/optimization/problems/{a['id']}")
    assert got.status_code == 200


def test_comparison_config_round_trips(container: AppContainer) -> None:
    from orbitmind.optimization import fixtures
    from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository

    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    thresholds = BenchmarkThresholds(competitive_relative_gap=0.25, min_feasible_sample_ratio=0.33)
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, thresholds=thresholds
    )
    session = container.database.session()
    stored = SqlAlchemyOptimizationRepository(session).get_comparison(run.id)
    session.close()
    assert stored is not None
    # Stored thresholds round-trip EXACTLY (not silently replaced by defaults; finding #12).
    assert stored.thresholds.competitive_relative_gap == 0.25
    assert stored.thresholds.min_feasible_sample_ratio == 0.33
    assert stored.epistemic_status == run.comparison.epistemic_status
    assert stored.limitations == run.comparison.limitations
    assert stored.conclusion == run.comparison.conclusion
