"""Coordinated parent+child sample forgery + independent scalar recomputation.

Final acceptance — Critical 1: a coordinated mutation of BOTH the parent experiment_json sample
and the matching quantum_sample_results child row (so the two agree) must still fail, because
every scientific sample scalar is independently recomputed from the canonical problem + bitstring
and the immutable signed receipt binds every persisted sample field.
"""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_models import (
    QuantumExperimentRow,
    QuantumSampleResultRow,
)
from orbitmind.quantum.adapter import quantum_available


def _quantum_benchmark(container: AppContainer):
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    assert svc.read_benchmark_evidence(run.id).authenticated
    return run, q


def _coordinated_mutate(container: AppContainer, experiment_id: str, field: str, delta: float):
    """Mutate the SAME first sample coherently in the parent JSON + the child row."""
    session = container.database.session()
    qrow = session.get(QuantumExperimentRow, experiment_id)
    blob = dict(qrow.experiment_json)
    samples = [dict(s) for s in blob["samples"]]
    target_bits = samples[0]["bitstring"]
    samples[0][field] = float(samples[0][field]) + delta
    blob["samples"] = samples
    qrow.experiment_json = blob
    child = (
        session.query(QuantumSampleResultRow)
        .filter_by(experiment_id=experiment_id, bitstring=target_bits)
        .first()
    )
    child.__setattr__(field, float(getattr(child, field)) + delta)
    session.commit()
    session.close()


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
@pytest.mark.parametrize(
    "field,delta",
    [
        ("raw_mission_value", 100.0),
        ("objective_value", 100.0),
        ("qubo_energy", 50.0),
        ("probability", 0.123),
    ],
)
def test_coordinated_parent_child_sample_forgery_fails(
    container: AppContainer, field: str, delta: float
) -> None:
    run, q = _quantum_benchmark(container)
    _coordinated_mutate(container, q.id, field, delta)
    auth = container.optimization_service.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
    assert auth.safe_conclusion() == "insufficient-evidence"


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
def test_coordinated_feasibility_forgery_fails(container: AppContainer) -> None:
    run, q = _quantum_benchmark(container)
    session = container.database.session()
    qrow = session.get(QuantumExperimentRow, q.id)
    blob = dict(qrow.experiment_json)
    samples = [dict(s) for s in blob["samples"]]
    bits = samples[0]["bitstring"]
    samples[0]["feasible"] = not samples[0]["feasible"]
    blob["samples"] = samples
    qrow.experiment_json = blob
    child = (
        session.query(QuantumSampleResultRow).filter_by(experiment_id=q.id, bitstring=bits).first()
    )
    child.feasible = not child.feasible
    session.commit()
    session.close()
    auth = container.optimization_service.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
