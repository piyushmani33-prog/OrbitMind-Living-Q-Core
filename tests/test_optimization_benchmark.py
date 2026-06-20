"""Unit tests: comparison-conclusion policy + full benchmark + verification."""

from __future__ import annotations

from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import conclude, run_benchmark
from orbitmind.optimization.models import (
    BenchmarkThresholds,
    ComparisonConclusion,
    ExperimentStatus,
    OptimalityStatus,
    QuantumExperiment,
    QuantumSampleResult,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark

_THRESH = BenchmarkThresholds(competitive_relative_gap=0.0, min_feasible_sample_ratio=0.05)


def _solver(kind: SolverKind, obj: float | None, feasible: bool, optimal: bool) -> SolverResult:
    return SolverResult(
        solver_kind=kind,
        solver_name=kind.value,
        solver_version="1.0",
        problem_checksum="x",
        configuration=SolverConfiguration(solver_kind=kind),
        status=ExperimentStatus.COMPLETED,
        optimality_status=OptimalityStatus.OPTIMAL if optimal else OptimalityStatus.FEASIBLE,
        objective_value=obj,
        feasible=feasible,
    )


def _quantum(best_obj: float | None, ratio: float, status: ExperimentStatus) -> QuantumExperiment:
    best = (
        QuantumSampleResult(
            bitstring="0110",
            count=10,
            probability=0.5,
            feasible=True,
            raw_mission_value=best_obj,
            objective_value=best_obj,
            qubo_energy=-best_obj,
            violations_count=0,
        )
        if best_obj is not None
        else None
    )
    return QuantumExperiment(
        problem_checksum="x",
        status=status,
        configuration=SolverConfiguration(solver_kind=SolverKind.QUANTUM_QAOA),
        best_feasible_sample=best,
        feasible_sample_ratio=ratio,
    )


def test_conclusion_classical_exact_best_without_quantum() -> None:
    c, _ = conclude(
        exact_result=_solver(SolverKind.EXACT, 10.0, True, True),
        greedy_result=_solver(SolverKind.GREEDY, 8.0, True, False),
        quantum_experiment=None,
        thresholds=_THRESH,
    )
    assert c == ComparisonConclusion.CLASSICAL_EXACT_BEST


def test_conclusion_classical_greedy_best_when_no_exact_optimum() -> None:
    c, _ = conclude(
        exact_result=None,
        greedy_result=_solver(SolverKind.GREEDY, 8.0, True, False),
        quantum_experiment=None,
        thresholds=_THRESH,
    )
    assert c == ComparisonConclusion.CLASSICAL_GREEDY_BEST


def test_conclusion_quantum_competitive() -> None:
    c, _ = conclude(
        exact_result=_solver(SolverKind.EXACT, 10.0, True, True),
        greedy_result=_solver(SolverKind.GREEDY, 10.0, True, False),
        quantum_experiment=_quantum(10.0, 1.0, ExperimentStatus.COMPLETED),
        thresholds=_THRESH,
    )
    assert c == ComparisonConclusion.QUANTUM_COMPETITIVE


def test_conclusion_quantum_worse() -> None:
    c, _ = conclude(
        exact_result=_solver(SolverKind.EXACT, 10.0, True, True),
        greedy_result=_solver(SolverKind.GREEDY, 5.0, True, False),
        quantum_experiment=_quantum(7.0, 1.0, ExperimentStatus.COMPLETED),
        thresholds=_THRESH,
    )
    assert c == ComparisonConclusion.QUANTUM_WORSE


def test_conclusion_equivalent_objective_when_optimum_unproven() -> None:
    # No proven optimum (exact unavailable); quantum exactly ties the best classical (greedy).
    c, _ = conclude(
        exact_result=None,
        greedy_result=_solver(SolverKind.GREEDY, 8.0, True, False),
        quantum_experiment=_quantum(8.0, 1.0, ExperimentStatus.COMPLETED),
        thresholds=_THRESH,
    )
    assert c == ComparisonConclusion.EQUIVALENT_OBJECTIVE


def test_conclusion_quantum_infeasible_and_failed_and_insufficient() -> None:
    base_exact = _solver(SolverKind.EXACT, 10.0, True, True)
    base_greedy = _solver(SolverKind.GREEDY, 10.0, True, False)
    infeasible, _ = conclude(
        exact_result=base_exact,
        greedy_result=base_greedy,
        quantum_experiment=_quantum(None, 0.0, ExperimentStatus.COMPLETED),
        thresholds=_THRESH,
    )
    assert infeasible == ComparisonConclusion.QUANTUM_INFEASIBLE
    failed, _ = conclude(
        exact_result=base_exact,
        greedy_result=base_greedy,
        quantum_experiment=_quantum(10.0, 1.0, ExperimentStatus.FAILED),
        thresholds=_THRESH,
    )
    assert failed == ComparisonConclusion.EXPERIMENT_FAILED
    insufficient, _ = conclude(
        exact_result=base_exact,
        greedy_result=base_greedy,
        quantum_experiment=_quantum(10.0, 0.01, ExperimentStatus.COMPLETED),
        thresholds=_THRESH,
    )
    assert insufficient == ComparisonConclusion.INSUFFICIENT_EVIDENCE


def test_full_benchmark_same_instance_and_verifies_clean() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    run = run_benchmark(p, seed=7, run_quantum=False)
    # Same normalized instance across solvers.
    checksums = {r.problem_checksum for r in run.solver_results} | {run.problem_checksum}
    assert checksums == {p.checksum}
    findings = verify_benchmark(p, run)
    assert all_critical_passed(findings)
    assert run.comparison.conclusion == ComparisonConclusion.CLASSICAL_EXACT_BEST


def test_verification_detects_tampered_objective() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    run = run_benchmark(p, seed=7, run_quantum=False)
    # Tamper a solver result's reported objective; the independent verifier must catch it.
    tampered = run.solver_results[0].model_copy(update={"objective_value": 999.0})
    run = run.model_copy(update={"solver_results": [tampered, run.solver_results[1]]})
    findings = verify_benchmark(p, run)
    assert not all_critical_passed(findings)
