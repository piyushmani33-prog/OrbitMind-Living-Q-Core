"""Integration tests for the bounded optimization API + memory links + Aer guard."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.container import AppContainer

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
