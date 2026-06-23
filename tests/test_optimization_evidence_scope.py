"""Benchmark-scoped evidence graphs (fifth review, High #3).

Two accepted benchmarks share one problem; tampering benchmark A must not affect benchmark B's
edges, and each graph shows ONLY its own benchmark's edges.
"""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from tests.test_optimization_read_auth import _tamper_exact_objective


@pytest.fixture
def client_container(container: AppContainer):
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    with TestClient(create_app(container)) as client:
        yield client, container


def _graph(client, bid: str) -> dict:
    return client.get(f"/api/v1/optimization/benchmarks/{bid}/evidence-graph").json()


def _generic(client, problem_id: str, **params) -> dict:
    return client.get(f"/api/v1/memory/graph/{problem_id}/neighbors", params=params).json()


def test_generic_problem_navigation_is_integrity_aware(client_container) -> None:
    # Final acceptance, High #3: the GENERIC memory navigation must authenticate each benchmark
    # independently — tampering A marks only A's edges invalid; B stays valid; both distinguishable.
    client, container = client_container
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run_a, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    run_b, _ = svc.benchmark(problem.id, seed=11, run_quantum=False)

    before = _generic(client, problem.id, limit=200)
    opt_edges = [n for n in before["neighbors"] if n["benchmark_id"] is not None]
    assert opt_edges and all(n["evidence_validity"] == "valid" for n in opt_edges)
    assert {run_a.id, run_b.id} <= {n["benchmark_id"] for n in opt_edges}

    _tamper_exact_objective(container, run_a.id)
    after = _generic(client, problem.id, limit=200)
    a_edges = [n for n in after["neighbors"] if n["benchmark_id"] == run_a.id]
    b_edges = [n for n in after["neighbors"] if n["benchmark_id"] == run_b.id]
    assert a_edges and all(n["evidence_validity"] == "integrity-failed" for n in a_edges)
    assert b_edges and all(n["evidence_validity"] == "valid" for n in b_edges)

    # valid_only filters out A's invalid edges; B's remain (history still stored).
    filtered = _generic(client, problem.id, limit=200, valid_only=True)
    assert all(n["benchmark_id"] != run_a.id for n in filtered["neighbors"] if n["benchmark_id"])
    assert any(n["benchmark_id"] == run_b.id for n in filtered["neighbors"])
    # The original edges are retained for forensics (default view still lists A's edges).
    assert any(n["benchmark_id"] == run_a.id for n in after["neighbors"])


def test_evidence_graph_is_benchmark_scoped(client_container) -> None:
    client, container = client_container
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run_a, _ = svc.benchmark(problem.id, seed=7, run_quantum=False)
    run_b, _ = svc.benchmark(problem.id, seed=11, run_quantum=False)
    assert run_a.id != run_b.id

    graph_a = _graph(client, run_a.id)
    graph_b = _graph(client, run_b.id)
    # Each graph shows ONLY its own benchmark's edges (entity ids belong to that run's children).
    a_solver_ids = {r.id for r in run_a.solver_results}
    b_solver_ids = {r.id for r in run_b.solver_results}
    a_entities = {e["entity_id"] for e in graph_a["edges"]}
    b_entities = {e["entity_id"] for e in graph_b["edges"]}
    assert graph_a["edges"] and graph_b["edges"]
    assert a_entities & b_solver_ids == set()  # no leakage of B's solver runs into A
    assert b_entities & a_solver_ids == set()
    assert graph_a["valid_evidence"] and graph_b["valid_evidence"]

    # Tamper benchmark A only.
    _tamper_exact_objective(container, run_a.id)
    graph_a2 = _graph(client, run_a.id)
    graph_b2 = _graph(client, run_b.id)
    # A is integrity-failed and all its edges flagged; B remains valid + unaffected.
    assert graph_a2["integrity_failed"] and not graph_a2["valid_evidence"]
    assert graph_a2["edges"] and all(e["integrity_failed"] for e in graph_a2["edges"])
    assert not graph_b2["integrity_failed"] and graph_b2["valid_evidence"]
    assert graph_b2["edges"] and all(not e["integrity_failed"] for e in graph_b2["edges"])
    # Original edges are retained for history (B still has the same edge count).
    assert len(graph_b2["edges"]) == len(graph_b["edges"])
