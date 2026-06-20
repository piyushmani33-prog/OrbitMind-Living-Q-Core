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


def test_bitorder_selected_schedule_matches_decode() -> None:
    p, qe = _experiment()
    ev = Evaluator(p)
    selected = qe.selected_schedule.selected_opportunity_ids
    assert (
        selected
        == ev.evaluate_bitstring(qe.best_feasible_sample.bitstring).selected_opportunity_ids
    )
