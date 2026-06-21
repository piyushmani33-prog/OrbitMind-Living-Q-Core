"""Zero objectives + unknown solver kinds (second Codex review, Medium finding #18).

A genuine 0.0 objective must verify as 0.0 (not be corrupted into NaN by `value or nan`
truthiness), and an unsupported/unknown solver kind in the comparison must yield a
deterministic CRITICAL finding rather than a KeyError.
"""

from __future__ import annotations

import datetime as dt

from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.models import (
    ConstraintSet,
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    SchedulingObjective,
    SchedulingProblem,
    SolverKind,
    TimeWindow,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark

_B = dt.datetime(2026, 6, 21, 10, 0, 0, tzinfo=dt.UTC)


def _win(a: int, b: int) -> TimeWindow:
    return TimeWindow(start=_B + dt.timedelta(minutes=a), end=_B + dt.timedelta(minutes=b))


def _zero_value_problem() -> SchedulingProblem:
    opps = [
        ObservationOpportunity(
            id="OPP-1",
            satellite_id="SAT-A",
            target_id="T1",
            window=_win(0, 30),
            mission_value=0.0,
            duration_seconds=1800.0,
            energy_cost=1.0,
            storage_cost=1.0,
        ),
        ObservationOpportunity(
            id="OPP-2",
            satellite_id="SAT-A",
            target_id="T1",
            window=_win(40, 70),
            mission_value=0.0,
            duration_seconds=1800.0,
            energy_cost=1.0,
            storage_cost=1.0,
        ),
    ]
    return normalize_problem(
        SchedulingProblem(
            name="all-zero",
            opportunities=opps,
            satellites=[
                SatelliteResource(id="SAT-A", energy_capacity=100.0, storage_capacity=100.0)
            ],
            targets=[ObservationTarget(id="T1")],
            constraints=ConstraintSet(),
            objective=SchedulingObjective(),
        )
    )


def test_all_zero_objective_benchmark_verifies() -> None:
    p = _zero_value_problem()
    run = run_benchmark(p, seed=7, run_quantum=False)
    findings = verify_benchmark(p, run)
    assert all_critical_passed(findings)
    # The zero objective survives as a real 0.0 (not corrupted into NaN).
    assert run.comparison.exact_objective == 0.0
    assert run.comparison.greedy_objective == 0.0
    assert run.comparison.known_optimum == 0.0


def test_zero_exact_objective_is_not_nan() -> None:
    p = _zero_value_problem()
    run = run_benchmark(p, seed=1, run_quantum=False)
    exact = next(r for r in run.solver_results if r.solver_kind == SolverKind.EXACT)
    assert exact.objective_value == 0.0
    # The exact-resolve verification check must pass for the zero objective.
    findings = {f.check_id: f for f in verify_benchmark(p, run)}
    assert findings["opt.exact_matches_independent_resolve"].passed
    assert findings["opt.objective_recompute.exact"].passed


def test_unknown_solver_kind_yields_critical_not_keyerror() -> None:
    p = _zero_value_problem()
    run = run_benchmark(p, seed=1, run_quantum=False)
    # Inject a quantum-kind result into the CLASSICAL results (a malformed enumeration).
    fake = run.solver_results[0].model_copy(update={"solver_kind": SolverKind.QUANTUM_QAOA})
    tampered = run.model_copy(update={"solver_results": [*run.solver_results, fake]})
    findings = verify_benchmark(p, tampered)  # must not raise KeyError
    bad = [f for f in findings if f.check_id.startswith("opt.unsupported_solver_kind")]
    assert bad and not bad[0].passed
    assert not all_critical_passed(findings)


def test_duplicated_unknown_solver_kind_still_handled() -> None:
    p = _zero_value_problem()
    run = run_benchmark(p, seed=1, run_quantum=False)
    fake = run.solver_results[0].model_copy(update={"solver_kind": SolverKind.QUANTUM_QAOA})
    tampered = run.model_copy(update={"solver_results": [*run.solver_results, fake, fake]})
    findings = verify_benchmark(p, tampered)  # two unknown-kind rows, still no crash
    bad = [f for f in findings if f.check_id.startswith("opt.unsupported_solver_kind")]
    assert len(bad) == 2 and not all_critical_passed(findings)
