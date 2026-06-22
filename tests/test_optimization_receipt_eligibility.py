"""Receipts are issued only for completed quantum workers (fourth review, Critical #1)."""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import benchmark as bench_mod
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import (
    ExperimentStatus,
    QuantumCircuitMetadata,
    QuantumExperiment,
    QuantumSampleResult,
    SolverConfiguration,
    SolverKind,
)
from orbitmind.optimization.receipts import quantum_execution_receipt_eligible
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository
from orbitmind.quantum.adapter import quantum_available

_NONCE = "a" * 32  # 16 bytes hex


def _completed_experiment(nonce: str = _NONCE) -> QuantumExperiment:
    meta = QuantumCircuitMetadata(
        qubits=4,
        depth=3,
        gate_counts={"h": 4},
        shots=8,
        optimizer_iterations=1,
        qaoa_layers=1,
        simulator_backend="AerSimulator",
        transpile_level=1,
        seed_simulator=7,
        seed_transpiler=7,
    )
    sample = QuantumSampleResult(
        bitstring="0000",
        count=8,
        probability=1.0,
        feasible=True,
        raw_mission_value=0.0,
        objective_value=0.0,
        qubo_energy=0.0,
        violations_count=0,
    )
    return QuantumExperiment(
        problem_checksum="x",
        status=ExperimentStatus.COMPLETED,
        configuration=SolverConfiguration(solver_kind=SolverKind.QUANTUM_QAOA, seed=7, shots=8),
        circuit_metadata=meta,
        samples=[sample],
        total_shots=8,
        execution_nonce=nonce,
    )


def test_eligible_only_when_completed_with_valid_nonce() -> None:
    assert quantum_execution_receipt_eligible(_completed_experiment()) is True
    assert quantum_execution_receipt_eligible(None) is False
    # Non-completed status, regardless of other fields, is never eligible.
    for st in (
        ExperimentStatus.TIMED_OUT,
        ExperimentStatus.FAILED,
        ExperimentStatus.CANCELLED,
        ExperimentStatus.UNSUPPORTED,
        ExperimentStatus.INCONCLUSIVE,
    ):
        assert not quantum_execution_receipt_eligible(
            _completed_experiment().model_copy(update={"status": st})
        )
    # Missing / short / non-hex / parent-style nonce is rejected.
    for bad in ("", "abc", "ZZZZ" * 8, "not-hex-value-aaaaaaaaaaaaaaaaaaaa"):
        assert not quantum_execution_receipt_eligible(_completed_experiment(nonce=bad))
    # No circuit metadata / no samples is not eligible.
    assert not quantum_execution_receipt_eligible(
        _completed_experiment().model_copy(update={"circuit_metadata": None})
    )
    assert not quantum_execution_receipt_eligible(
        _completed_experiment().model_copy(update={"samples": []})
    )


@pytest.mark.parametrize(
    "status",
    [
        ExperimentStatus.TIMED_OUT,
        ExperimentStatus.FAILED,
        ExperimentStatus.CANCELLED,
        ExperimentStatus.UNSUPPORTED,
        ExperimentStatus.INCONCLUSIVE,
    ],
)
def test_non_completed_quantum_gets_no_receipt_and_stays_unaccepted(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch, status: ExperimentStatus
) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))

    def _fake(problem, config, evaluator=None, **kw):  # type: ignore[no-untyped-def]
        return QuantumExperiment(
            problem_checksum=problem.checksum, status=status, configuration=config, seed=config.seed
        )

    monkeypatch.setattr(bench_mod, "run_quantum_experiment", _fake)
    monkeypatch.setattr(bench_mod, "quantum_available", lambda: True)
    run, findings = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=True)

    receipt_finding = next(f for f in findings if f.check_id == "opt.execution_receipt")
    assert not receipt_finding.passed
    assert run.comparison is not None
    assert run.comparison.conclusion.value == "insufficient-evidence"
    session = container.database.session()
    repo = SqlAlchemyOptimizationRepository(session)
    accepted = repo.get_benchmark(run.id)
    receipt = repo.get_receipt(run.id)
    session.close()
    assert accepted is not None and accepted.verification_passed is False
    assert receipt is None  # parent never fabricates a nonce / receipt for an incomplete run
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert neighbors.neighbors == []


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
def test_completed_runs_share_outputs_but_have_distinct_nonces_and_receipts(
    container: AppContainer,
) -> None:
    svc = container.optimization_service
    p1 = svc.create_problem(fixtures.fixture("default"))
    run_a, _ = svc.benchmark(p1.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    run_b, _ = svc.benchmark(p1.id, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    qa, qb = run_a.quantum_experiment, run_b.quantum_experiment
    if qa is None or qb is None or qa.status.value != "completed" or qb.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    # Identical deterministic scientific output ...
    assert [s.bitstring for s in qa.samples] == [s.bitstring for s in qb.samples]
    assert [s.count for s in qa.samples] == [s.count for s in qb.samples]
    # ... but distinct worker nonces => distinct receipts.
    assert qa.execution_nonce and qb.execution_nonce and qa.execution_nonce != qb.execution_nonce
    session = container.database.session()
    repo = SqlAlchemyOptimizationRepository(session)
    ra, rb = repo.get_receipt(run_a.id), repo.get_receipt(run_b.id)
    session.close()
    assert ra is not None and rb is not None and ra.signature != rb.signature
