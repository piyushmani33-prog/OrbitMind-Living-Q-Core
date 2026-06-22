"""Canonical persisted-evidence authentication + fail-closed malformed handling.

Fifth review — Critical (duplicate sample representations must agree) and High #2 (malformed
persisted evidence must fail closed, never raise / 500).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_models import (
    QuantumExperimentRow,
    QuantumSampleResultRow,
    SolverRunRow,
)
from orbitmind.quantum.adapter import quantum_available


def _integrity_audits(container: AppContainer) -> int:
    with container.database.engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action='optimization.benchmark_integrity_failed'"
                )
            ).scalar_one()
        )


# --- Critical: the persisted child sample rows are authoritative-equal to the parent samples ---
@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
def test_child_sample_row_tamper_fails_reauth(container: AppContainer) -> None:
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    # Untampered evidence authenticates.
    assert svc.read_benchmark_evidence(run.id).authenticated

    # Tamper ONLY the child quantum_sample_results row (the parent experiment_json is untouched,
    # so semantic re-verification alone would not notice).
    session = container.database.session()
    row = session.query(QuantumSampleResultRow).filter_by(experiment_id=q.id).first()
    assert row is not None
    row.raw_mission_value = float(row.raw_mission_value) + 123.0
    session.commit()
    session.close()

    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
    assert auth.integrity_status == "sample-row-mismatch"
    assert auth.safe_conclusion() == "insufficient-evidence"
    assert _integrity_audits(container) >= 1


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
def test_child_sample_feasibility_tamper_fails_reauth(container: AppContainer) -> None:
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    session = container.database.session()
    row = session.query(QuantumSampleResultRow).filter_by(experiment_id=q.id).first()
    assert row is not None
    row.feasible = not row.feasible
    session.commit()
    session.close()
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and auth.integrity_status == "sample-row-mismatch"


# --- High 2: malformed persisted JSON fails closed (no uncaught exception / 500) ---
def _classical_benchmark(container: AppContainer) -> str:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    return run.id


def test_malformed_solver_json_fails_closed(container: AppContainer) -> None:
    bid = _classical_benchmark(container)
    session = container.database.session()
    row = session.query(SolverRunRow).filter_by(benchmark_id=bid).first()
    assert row is not None
    row.result_json = {"not": "a valid solver result"}
    session.commit()
    session.close()
    auth = container.optimization_service.read_benchmark_evidence(bid)
    assert auth.found and auth.integrity_failed and auth.run is None
    assert auth.integrity_status == "malformed-persisted-evidence"
    assert _integrity_audits(container) >= 1


def test_malformed_evidence_endpoints_do_not_500(client_container) -> None:
    client, container = client_container
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    session = container.database.session()
    row = session.query(SolverRunRow).filter_by(benchmark_id=run.id).first()
    assert row is not None
    row.result_json = {"corrupt": True}
    session.commit()
    session.close()

    # Benchmark read: bounded integrity error (422), not a 500 and not a positive serve.
    assert client.get(f"/api/v1/optimization/benchmarks/{run.id}").status_code == 422
    # Artifacts: withheld with a bounded error, not a 500.
    assert client.get(f"/api/v1/optimization/runs/{run.id}/artifacts").status_code == 422
    # Run list: returns 200 and marks the malformed run integrity-failed (no exception).
    listing = client.get("/api/v1/optimization/runs")
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["id"] == run.id)
    assert item["integrity_failed"] and not item["verified"]
    # Evidence graph: bounded, no valid evidence, no 500.
    graph = client.get(f"/api/v1/optimization/benchmarks/{run.id}/evidence-graph")
    assert graph.status_code == 200
    assert graph.json()["integrity_failed"] and not graph.json()["valid_evidence"]


def test_malformed_quantum_json_fails_closed(container: AppContainer) -> None:
    # A corrupt quantum experiment_json must classify as malformed, not raise.
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    session = container.database.session()
    # Inject a malformed quantum row directly (no valid quantum run on a classical benchmark).
    session.add(
        QuantumExperimentRow(
            id="q-malformed",
            benchmark_id=run.id,
            problem_id=run.problem_id,
            problem_checksum=run.problem_checksum,
            status="completed",
            shots=1,
            optimizer_iterations=1,
            qaoa_layers=1,
            total_shots=1,
            distinct_samples=0,
            feasible_sample_ratio=0.0,
            seed=1,
            runtime_seconds=0.0,
            experiment_json={"garbage": 1},
            software_versions={},
            created_at=__import__("orbitmind.core.timeutils", fromlist=["utcnow"]).utcnow(),
        )
    )
    session.commit()
    session.close()
    auth = container.optimization_service.read_benchmark_evidence(run.id)
    assert auth.found and auth.integrity_failed
    assert auth.integrity_status == "malformed-persisted-evidence"


def test_overclaim_injected_into_comparison_limitations_fails_reauth(
    container: AppContainer,
) -> None:
    # Limitations text is scientific evidence: an affirmative claim injected after acceptance must
    # invalidate read authentication (fifth review, Critical step 6).
    from orbitmind.persistence.optimization_models import BenchmarkComparisonRow

    bid = _classical_benchmark(container)
    assert container.optimization_service.read_benchmark_evidence(bid).authenticated
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    assert row is not None
    row.limitations = "quantum advantage verified on this instance"
    session.commit()
    session.close()
    auth = container.optimization_service.read_benchmark_evidence(bid)
    assert auth.integrity_failed and not auth.authenticated


@pytest.fixture
def client_container(container: AppContainer):
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    with TestClient(create_app(container)) as client:
        yield client, container
