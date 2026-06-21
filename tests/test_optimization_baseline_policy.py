"""Classical baseline cardinality/authentication + server-owned policy (High finding #2).

Table-driven: every malformed or tampered comparison must FAIL verification (no invalid case
may pass a CRITICAL check), and the runtime conclusion policy must never award a positive
conclusion when a classical baseline failed/timed-out/cancelled/missing.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import conclude, run_benchmark
from orbitmind.optimization.models import (
    BenchmarkRun,
    ComparisonConclusion,
    ExperimentStatus,
    OptimalityStatus,
    SolverKind,
)
from orbitmind.optimization.policy import default_policy, get_policy
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark

_PROBLEM = normalize_problem(fixtures.fixture("default"))


def _base_run() -> BenchmarkRun:
    return run_benchmark(_PROBLEM, seed=7, run_quantum=False)


def _exact(run: BenchmarkRun):
    return next(r for r in run.solver_results if r.solver_kind == SolverKind.EXACT)


def _greedy(run: BenchmarkRun):
    return next(r for r in run.solver_results if r.solver_kind == SolverKind.GREEDY)


def test_untampered_run_verifies() -> None:
    assert all_critical_passed(verify_benchmark(_PROBLEM, _base_run()))


def _missing_exact(run: BenchmarkRun) -> BenchmarkRun:
    return run.model_copy(update={"solver_results": [_greedy(run)]})


def _missing_greedy(run: BenchmarkRun) -> BenchmarkRun:
    return run.model_copy(update={"solver_results": [_exact(run)]})


def _duplicate_exact(run: BenchmarkRun) -> BenchmarkRun:
    dup = _exact(run).model_copy(update={"id": "dup-exact"})
    return run.model_copy(update={"solver_results": [*run.solver_results, dup]})


def _duplicate_greedy(run: BenchmarkRun) -> BenchmarkRun:
    dup = _greedy(run).model_copy(update={"id": "dup-greedy"})
    return run.model_copy(update={"solver_results": [*run.solver_results, dup]})


def _reused_id(run: BenchmarkRun) -> BenchmarkRun:
    g = _greedy(run).model_copy(update={"id": _exact(run).id})  # id reused across kinds
    return run.model_copy(update={"solver_results": [_exact(run), g]})


def _exact_claims_one_candidate(run: BenchmarkRun) -> BenchmarkRun:
    ex = _exact(run)
    forged = ex.model_copy(
        update={"resource_usage": ex.resource_usage.model_copy(update={"evaluated_candidates": 1})}
    )
    return run.model_copy(update={"solver_results": [forged, _greedy(run)]})


def _exact_timed_out(run: BenchmarkRun) -> BenchmarkRun:
    ex = _exact(run).model_copy(
        update={
            "status": ExperimentStatus.TIMED_OUT,
            "optimality_status": OptimalityStatus.FEASIBLE,
        }
    )
    return run.model_copy(update={"solver_results": [ex, _greedy(run)]})


def _exact_failed_stale_objective(run: BenchmarkRun) -> BenchmarkRun:
    ex = _exact(run).model_copy(update={"status": ExperimentStatus.FAILED})  # keeps stale objective
    return run.model_copy(update={"solver_results": [ex, _greedy(run)]})


def _greedy_failed(run: BenchmarkRun) -> BenchmarkRun:
    g = _greedy(run).model_copy(update={"status": ExperimentStatus.FAILED})
    return run.model_copy(update={"solver_results": [_exact(run), g]})


def _unknown_kind(run: BenchmarkRun) -> BenchmarkRun:
    fake = _exact(run).model_copy(update={"solver_kind": SolverKind.QUANTUM_QAOA, "id": "q"})
    return run.model_copy(update={"solver_results": [*run.solver_results, fake]})


def _solver_from_another_problem(run: BenchmarkRun) -> BenchmarkRun:
    ex = _exact(run).model_copy(update={"problem_checksum": "deadbeef"})
    return run.model_copy(update={"solver_results": [ex, _greedy(run)]})


def _forged_threshold_and_conclusion(run: BenchmarkRun) -> BenchmarkRun:
    # Coherently change the persisted threshold AND the conclusion. The verifier uses SERVER
    # thresholds (registry), so the forgery is rejected.
    lenient = get_policy("lenient-v1")
    assert lenient is not None and run.comparison is not None
    comp = run.comparison.model_copy(
        update={
            "thresholds": lenient.thresholds(),
            "conclusion": ComparisonConclusion.QUANTUM_COMPETITIVE,
        }
    )
    return run.model_copy(update={"comparison": comp})


def _forged_policy_id(run: BenchmarkRun) -> BenchmarkRun:
    assert run.comparison is not None
    comp = run.comparison.model_copy(update={"policy_id": "no-such-policy"})
    return run.model_copy(update={"comparison": comp})


_TAMPERS: list[tuple[str, Callable[[BenchmarkRun], BenchmarkRun]]] = [
    ("missing_exact", _missing_exact),
    ("missing_greedy", _missing_greedy),
    ("duplicate_exact", _duplicate_exact),
    ("duplicate_greedy", _duplicate_greedy),
    ("reused_id_across_kinds", _reused_id),
    ("exact_claims_one_candidate", _exact_claims_one_candidate),
    ("exact_timed_out", _exact_timed_out),
    ("exact_failed_stale_objective", _exact_failed_stale_objective),
    ("greedy_failed", _greedy_failed),
    ("unknown_solver_kind", _unknown_kind),
    ("solver_from_another_problem", _solver_from_another_problem),
    ("forged_threshold_and_conclusion", _forged_threshold_and_conclusion),
    ("forged_policy_id", _forged_policy_id),
]


@pytest.mark.parametrize("name,tamper", _TAMPERS, ids=[n for n, _ in _TAMPERS])
def test_tampered_comparison_fails_verification(
    name: str, tamper: Callable[[BenchmarkRun], BenchmarkRun]
) -> None:
    tampered = tamper(_base_run())
    findings = verify_benchmark(_PROBLEM, tampered)  # never raises
    assert not all_critical_passed(findings), f"{name} should fail a CRITICAL verification check"


# ---- runtime conclusion policy: failed/timed-out baselines are never positive --------------
def test_conclude_failed_exact_is_non_positive() -> None:
    run = _base_run()
    failed_exact = _exact(run).model_copy(
        update={"status": ExperimentStatus.FAILED, "feasible": False}
    )
    conclusion, _ = conclude(
        exact_result=failed_exact,
        greedy_result=_greedy(run),
        quantum_experiment=None,
        thresholds=default_policy().thresholds(),
    )
    # A failed exact contributes no proven optimum; greedy may still be the classical best, but
    # the stale exact objective must NOT be used.
    assert conclusion in (
        ComparisonConclusion.CLASSICAL_GREEDY_BEST,
        ComparisonConclusion.INSUFFICIENT_EVIDENCE,
    )


def test_conclude_both_baselines_failed_is_insufficient() -> None:
    run = _base_run()
    fe = _exact(run).model_copy(update={"status": ExperimentStatus.FAILED, "feasible": False})
    fg = _greedy(run).model_copy(update={"status": ExperimentStatus.FAILED, "feasible": False})
    conclusion, _ = conclude(
        exact_result=fe,
        greedy_result=fg,
        quantum_experiment=None,
        thresholds=default_policy().thresholds(),
    )
    assert conclusion == ComparisonConclusion.INSUFFICIENT_EVIDENCE
