"""Simulator-only QAOA experiment tests (offline; skip cleanly if Aer is absent)."""

from __future__ import annotations

import pytest

from orbitmind.optimization import fixtures
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ExperimentStatus,
    SolverConfiguration,
    SolverKind,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.quantum import run_quantum_experiment
from orbitmind.optimization.solvers import solve_exact
from orbitmind.quantum.adapter import quantum_available

pytestmark = [
    pytest.mark.quantum,
    pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed"),
]


def _config(**kw: object) -> SolverConfiguration:
    base: dict[str, object] = {
        "solver_kind": SolverKind.QUANTUM_QAOA,
        "seed": 7,
        "shots": 2048,
        "optimizer_iterations": 25,
    }
    base.update(kw)
    return SolverConfiguration(**base)  # type: ignore[arg-type]


def _experiment(name: str = "default", **cfg: object):
    p = normalize_problem(fixtures.fixture(name))
    ev = Evaluator(p)
    ex = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT), ev)
    return p, run_quantum_experiment(
        p,
        _config(**cfg),
        ev,
        known_optimum=ex.objective_value,
        optimum_selection=ex.schedule.selected_opportunity_ids,
    )


def test_experiment_is_simulator_only_with_recorded_metadata() -> None:
    _p, qe = _experiment()
    assert qe.status == ExperimentStatus.COMPLETED
    m = qe.circuit_metadata
    assert m is not None
    assert m.simulator_backend == "AerSimulator"
    assert m.qubits == 4 and m.depth > 0 and m.shots == 2048
    assert m.seed_simulator == 7 and m.seed_transpiler == 7
    assert m.gate_counts and m.optimizer_iterations > 0


def test_experiment_is_deterministic() -> None:
    _p1, a = _experiment()
    _p2, b = _experiment()
    assert [s.bitstring for s in a.samples] == [s.bitstring for s in b.samples]
    assert [s.count for s in a.samples] == [s.count for s in b.samples]
    assert a.best_feasible_sample.bitstring == b.best_feasible_sample.bitstring


def test_samples_are_independently_verified_and_feasible_selected() -> None:
    p, qe = _experiment()
    ev = Evaluator(p)
    best = qe.best_feasible_sample
    assert best is not None and best.feasible
    # The selected sample re-verifies feasible with the reported objective.
    recheck = ev.evaluate_bitstring(best.bitstring)
    assert recheck.feasible and recheck.objective_value == best.objective_value
    # best feasible is the max objective among feasible samples.
    feasible = [s for s in qe.samples if s.feasible]
    assert best.objective_value == max(s.objective_value for s in feasible)
    assert qe.exact_optimum_in_samples is True
    assert qe.objective_gap == 0.0


def test_infeasible_samples_preserved_for_diagnostics() -> None:
    # resource-bound has constraints not encoded in the QUBO -> some infeasible samples.
    _p, qe = _experiment("resource-bound")
    assert 0.0 < qe.feasible_sample_ratio < 1.0
    assert any(not s.feasible for s in qe.samples)  # infeasible samples kept
    assert qe.best_infeasible_sample is not None and not qe.best_infeasible_sample.feasible


def test_timeout_is_reported() -> None:
    _p, qe = _experiment(timeout_seconds=1e-9)
    assert qe.status == ExperimentStatus.TIMED_OUT


def test_whole_experiment_timeout_with_slow_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deliberately slow worker must NOT finish after the timeout (review finding #3):
    bounded wall-clock return, status timed-out, no completed evidence, no positive
    conclusion, and the worker process is cleaned up."""
    import time

    from orbitmind.optimization.benchmark import conclude
    from orbitmind.optimization.models import BenchmarkThresholds, ComparisonConclusion

    p = normalize_problem(fixtures.fixture("default"))
    ev = Evaluator(p)
    ex = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT), ev)
    # The worker will sleep far longer than the timeout (env var inherited by the spawned child).
    monkeypatch.setenv("ORBITMIND_QUANTUM_TEST_SLEEP", "120")
    started = time.perf_counter()
    qe = run_quantum_experiment(
        p, _config(timeout_seconds=4.0), ev, known_optimum=ex.objective_value
    )
    wall = time.perf_counter() - started
    assert qe.status == ExperimentStatus.TIMED_OUT
    assert wall < 30.0  # bounded; nowhere near the 120s slow-worker sleep
    assert qe.best_feasible_sample is None  # no final sampling completed
    assert qe.circuit_metadata is None
    assert "terminated" in qe.error.lower()
    # A timed-out quantum run can never receive a positive conclusion.
    conclusion, _ = conclude(
        exact_result=ex,
        greedy_result=None,
        quantum_experiment=qe,
        thresholds=BenchmarkThresholds(),
    )
    assert conclusion == ComparisonConclusion.INSUFFICIENT_EVIDENCE


def test_bitorder_selected_schedule_matches_decode() -> None:
    p, qe = _experiment()
    ev = Evaluator(p)
    selected = qe.selected_schedule.selected_opportunity_ids
    assert (
        selected
        == ev.evaluate_bitstring(qe.best_feasible_sample.bitstring).selected_opportunity_ids
    )


def test_worker_run_in_process_records_full_evidence() -> None:
    """Exercise the worker computation in-process (it normally runs in a child process, so
    coverage cannot otherwise see it). Verifies the self-describing evidence (finding #13)."""
    from orbitmind.optimization import quantum as q
    from orbitmind.optimization.models import QuantumExperiment

    p = normalize_problem(fixtures.fixture("default"))
    ev = Evaluator(p)
    ex = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT), ev)
    base = QuantumExperiment(
        problem_checksum=p.checksum,
        status=ExperimentStatus.PENDING,
        configuration=_config(),
        seed=7,
    )
    result = q._run(
        p, _config(), ev, base, ex.objective_value, ex.schedule.selected_opportunity_ids
    )
    assert result.status == ExperimentStatus.COMPLETED
    assert result.circuit_metadata is not None and result.circuit_metadata.qubits == 4
    ev_rec = result.evidence
    assert ev_rec is not None
    assert ev_rec.qubo_checksum and ev_rec.problem_checksum == p.checksum
    assert ev_rec.variable_mapping == ("OPP-1", "OPP-2", "OPP-3", "OPP-4")
    assert "no-overlap (same-satellite time conflicts)" in ev_rec.encoded_constraints
    assert "energy-capacity" in ev_rec.unencoded_constraints  # verifier-only
    assert ev_rec.penalty_sufficient is True
    assert ev_rec.post_verification_required is True
    assert ev_rec.seeds["seed_simulator"] == 7
