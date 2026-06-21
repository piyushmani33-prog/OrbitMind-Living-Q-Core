"""Codex remediation regression tests.

Includes an INDEPENDENT reference evaluator (test-local arithmetic) that does NOT import
the production evaluator / QUBO energy / penalty checker / comparison policy, so the same
implementation bug cannot appear on both sides of the test (review finding #20).
"""

from __future__ import annotations

import datetime as dt
import tempfile
from itertools import product
from pathlib import Path

import pytest

from orbitmind.core.errors import ValidationError
from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import conclude, proven_optimum, run_benchmark
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    BenchmarkThresholds,
    ComparisonConclusion,
    ConstraintSet,
    ExperimentStatus,
    OptimalityStatus,
    QuantumExperiment,
    QuantumSampleResult,
    SchedulingObjective,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.penalties import penalty_policy
from orbitmind.optimization.problem import normalize_problem, resolved_penalty, variable_order
from orbitmind.optimization.qubo import build_qubo, qubo_energy
from orbitmind.optimization.solvers import solve_exact, solve_greedy
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark

_NAMES = ("default", "resource-bound", "mutual-exclusion")


# ---------------------------------------------------------------------------
# Independent reference (explicit arithmetic; does not call production internals)
# ---------------------------------------------------------------------------
def _ref_conflict_pairs(problem) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    opps = problem.opportunities
    if problem.constraints.enforce_no_overlap:
        for i in range(len(opps)):
            for j in range(i + 1, len(opps)):
                a, b = opps[i], opps[j]
                overlap = a.window.start < b.window.end and b.window.start < a.window.end
                if a.satellite_id == b.satellite_id and overlap:
                    pairs.add(tuple(sorted((a.id, b.id))))  # type: ignore[arg-type]
    for a_id, b_id in problem.constraints.mutually_exclusive:
        pairs.add(tuple(sorted((a_id, b_id))))  # type: ignore[arg-type]
    return pairs


def _ref_penalty(problem) -> float:
    weight = problem.objective.mission_value_weight
    return sum(max(0.0, o.mission_value) for o in problem.opportunities) * weight + 1.0


def _ref_penalized_objective(problem, selected: set[str]) -> float:
    weight = problem.objective.mission_value_weight
    value = sum(o.mission_value for o in problem.opportunities if o.id in selected) * weight
    pairs = _ref_conflict_pairs(problem)
    mandatory = set(problem.constraints.mandatory)
    violations = sum(1 for a, b in pairs if a in selected and b in selected)
    violations += sum(1 for m in mandatory if m not in selected)
    return value - _ref_penalty(problem) * violations


@pytest.mark.parametrize("name", _NAMES)
def test_qubo_energy_matches_independent_reference(name: str) -> None:
    problem = normalize_problem(fixtures.fixture(name))
    order = variable_order(problem)
    qubo = build_qubo(problem)
    for bt in product("01", repeat=len(order)):
        bits = "".join(bt)
        selected = {order[i] for i, c in enumerate(bits) if c == "1"}
        ref = _ref_penalized_objective(problem, selected)
        # production QUBO energy must equal -(independent reference penalized objective)
        assert abs(qubo_energy(qubo, bits) - (-ref)) < 1e-9


def test_weighted_objective_matches_reference() -> None:
    base = fixtures.fixture("default")
    problem = normalize_problem(
        base.model_copy(update={"objective": SchedulingObjective(mission_value_weight=3.0)})
    )
    ev = Evaluator(problem)
    order = variable_order(problem)
    for bt in product("01", repeat=len(order)):
        bits = "".join(bt)
        selected = {order[i] for i, c in enumerate(bits) if c == "1"}
        assert (
            abs(
                ev.evaluate(selected).penalized_objective
                - _ref_penalized_objective(problem, selected)
            )
            < 1e-9
        )


def test_resolved_penalty_matches_reference() -> None:
    for name in _NAMES:
        p = normalize_problem(fixtures.fixture(name))
        assert abs(resolved_penalty(p) - _ref_penalty(p)) < 1e-9


# ---------------------------------------------------------------------------
# #4 problem validation
# ---------------------------------------------------------------------------
def _opp(oid: str, sat: str, tgt: str, s: int, e: int, val: float = 5.0):
    from orbitmind.optimization.models import ObservationOpportunity, TimeWindow

    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationOpportunity(
        id=oid,
        satellite_id=sat,
        target_id=tgt,
        window=TimeWindow(start=base + dt.timedelta(minutes=s), end=base + dt.timedelta(minutes=e)),
        mission_value=val,
        duration_seconds=(e - s) * 60.0,
        energy_cost=1.0,
        storage_cost=1.0,
    )


def _problem(**overrides):
    from orbitmind.optimization.models import (
        ObservationTarget,
        SatelliteResource,
        SchedulingProblem,
    )

    defaults: dict = {
        "name": "t",
        "opportunities": [_opp("OPP-1", "SAT-A", "T1", 0, 30)],
        "satellites": [
            SatelliteResource(id="SAT-A", energy_capacity=100.0, storage_capacity=100.0)
        ],
        "targets": [ObservationTarget(id="T1")],
    }
    defaults.update(overrides)
    return SchedulingProblem(**defaults)


def test_validation_rejects_empty_registries_and_bad_refs() -> None:
    with pytest.raises(ValidationError):
        normalize_problem(_problem(satellites=[]))
    with pytest.raises(ValidationError):
        normalize_problem(_problem(targets=[]))
    with pytest.raises(ValidationError):
        normalize_problem(_problem(opportunities=[_opp("OPP-1", "UNKNOWN", "T1", 0, 30)]))
    with pytest.raises(ValidationError):
        normalize_problem(_problem(opportunities=[_opp("OPP-1", "SAT-A", "UNKNOWN", 0, 30)]))


def test_validation_rejects_duplicate_and_self_mutex() -> None:
    with pytest.raises(ValidationError):
        normalize_problem(
            _problem(
                opportunities=[
                    _opp("OPP-1", "SAT-A", "T1", 0, 30),
                    _opp("OPP-1", "SAT-A", "T1", 40, 60),
                ]
            )
        )
    with pytest.raises(ValidationError):
        normalize_problem(
            _problem(constraints=ConstraintSet(mutually_exclusive=(("OPP-1", "OPP-1"),)))
        )


def test_validation_canonicalizes_to_utc_and_dedups_mutex() -> None:
    from orbitmind.optimization.models import (
        ObservationTarget,
        SatelliteResource,
        SchedulingProblem,
        TimeWindow,
    )

    tz = dt.timezone(dt.timedelta(hours=5))
    start = dt.datetime(2026, 6, 21, 15, 0, tzinfo=tz)
    p = SchedulingProblem(
        name="tz",
        opportunities=[
            _opp("OPP-1", "SAT-A", "T1", 0, 30).model_copy(
                update={"window": TimeWindow(start=start, end=start + dt.timedelta(minutes=30))}
            ),
            _opp("OPP-2", "SAT-A", "T2", 40, 70),
        ],
        satellites=[SatelliteResource(id="SAT-A", energy_capacity=100.0, storage_capacity=100.0)],
        targets=[ObservationTarget(id="T1"), ObservationTarget(id="T2")],
        constraints=ConstraintSet(mutually_exclusive=(("OPP-2", "OPP-1"), ("OPP-1", "OPP-2"))),
    )
    norm = normalize_problem(p)
    assert norm.opportunities[0].window.start.tzinfo == dt.UTC
    assert norm.opportunities[0].window.start.hour == 10  # 15:00+05 -> 10:00 UTC
    assert norm.constraints.mutually_exclusive == (("OPP-1", "OPP-2"),)  # deduped + sorted


def test_validation_rejects_duration_window_mismatch_and_nonfinite() -> None:
    bad_duration = _opp("OPP-1", "SAT-A", "T1", 0, 30).model_copy(
        update={"duration_seconds": 5400.0}
    )
    with pytest.raises(ValidationError):
        normalize_problem(_problem(opportunities=[bad_duration]))
    inf_obj = SchedulingObjective(mission_value_weight=float("inf"))
    with pytest.raises(ValidationError):
        normalize_problem(_problem(objective=inf_obj))


# ---------------------------------------------------------------------------
# #6 penalty policy + sufficiency
# ---------------------------------------------------------------------------
def test_penalty_rejects_unsafe_explicit_values() -> None:
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        p = _problem(objective=SchedulingObjective(penalty_coefficient=bad))
        with pytest.raises(ValidationError):
            resolved_penalty(p)


def test_penalty_too_small_is_reported_insufficient() -> None:
    from orbitmind.optimization.models import ObservationTarget

    # An explicit penalty <= the smaller value of a conflict pair lets the infeasible
    # "select both" assignment tie/beat the best feasible -> must be reported insufficient.
    p = normalize_problem(
        _problem(
            opportunities=[
                _opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0),
                _opp("OPP-2", "SAT-A", "T2", 5, 35, 6.0),  # overlaps OPP-1 -> conflict
            ],
            targets=[ObservationTarget(id="T1"), ObservationTarget(id="T2")],
            objective=SchedulingObjective(penalty_coefficient=5.0),  # == min(5, 6) -> a tie
        )
    )
    assert penalty_policy(p).sufficient is False
    # The auto penalty (total weighted value + 1) for the same instance IS sufficient.
    auto = normalize_problem(
        _problem(
            opportunities=[
                _opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0),
                _opp("OPP-2", "SAT-A", "T2", 5, 35, 6.0),
            ],
            targets=[ObservationTarget(id="T1"), ObservationTarget(id="T2")],
        )
    )
    assert penalty_policy(auto).sufficient is True


def test_penalty_detects_contradictory_mandatory_conflict() -> None:
    from orbitmind.optimization.models import ObservationTarget

    # Two mandatory opportunities that conflict -> no satisfying encoded assignment exists.
    p = normalize_problem(
        _problem(
            opportunities=[
                _opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0),
                _opp("OPP-2", "SAT-A", "T2", 5, 35, 6.0),
            ],
            targets=[ObservationTarget(id="T1"), ObservationTarget(id="T2")],
            constraints=ConstraintSet(mandatory=("OPP-1", "OPP-2")),
        )
    )
    policy = penalty_policy(p)
    assert policy.satisfying_encoded_assignment_exists is False
    assert policy.sufficient is False


# ---------------------------------------------------------------------------
# #8 greedy mandatory atomicity
# ---------------------------------------------------------------------------
def test_greedy_infeasible_mandatory_set_reported() -> None:
    from orbitmind.optimization.models import ObservationTarget

    p = normalize_problem(
        _problem(
            opportunities=[
                _opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0),
                _opp("OPP-2", "SAT-A", "T2", 5, 35, 6.0),  # conflicts OPP-1
            ],
            targets=[ObservationTarget(id="T1"), ObservationTarget(id="T2")],
            constraints=ConstraintSet(mandatory=("OPP-1", "OPP-2")),
        )
    )
    result = solve_greedy(p, SolverConfiguration(solver_kind=SolverKind.GREEDY))
    assert result.optimality_status == OptimalityStatus.INFEASIBLE
    assert not result.feasible


def test_greedy_seeds_full_mandatory_set() -> None:
    # resource-bound has mandatory OPP-4; greedy must include it atomically.
    p = normalize_problem(fixtures.fixture("resource-bound"))
    result = solve_greedy(p, SolverConfiguration(solver_kind=SolverKind.GREEDY))
    assert result.feasible and "OPP-4" in result.schedule.selected_opportunity_ids


# ---------------------------------------------------------------------------
# #10 known optimum + #17 exact immediate timeout
# ---------------------------------------------------------------------------
def test_proven_optimum_requires_completed_optimal() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    # Unsupported (size cap below n) -> not a known optimum.
    small = p.model_copy(update={"limits": p.limits.model_copy(update={"exact_max_variables": 2})})
    unsupported = solve_exact(small, SolverConfiguration(solver_kind=SolverKind.EXACT))
    assert proven_optimum(unsupported) == (None, None)
    # Immediate timeout -> not a known optimum; status timed-out, optimality unknown.
    timed = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT, timeout_seconds=1e-9))
    if timed.status == ExperimentStatus.TIMED_OUT:
        assert timed.optimality_status == OptimalityStatus.UNKNOWN
        assert timed.optimality_status != OptimalityStatus.INFEASIBLE
        assert proven_optimum(timed) == (None, None)


# ---------------------------------------------------------------------------
# #19 comparison policy: status guards before objective comparison
# ---------------------------------------------------------------------------
def _exact(obj: float) -> SolverResult:
    from orbitmind.optimization.models import CandidateSchedule

    return SolverResult(
        solver_kind=SolverKind.EXACT,
        solver_name="x",
        solver_version="1",
        problem_checksum="x",
        configuration=SolverConfiguration(solver_kind=SolverKind.EXACT),
        status=ExperimentStatus.COMPLETED,
        optimality_status=OptimalityStatus.OPTIMAL,
        objective_value=obj,
        feasible=True,
        schedule=CandidateSchedule(problem_checksum="x", selected_opportunity_ids=("OPP-1",)),
    )


def _quantum(status: ExperimentStatus, with_best: bool = True) -> QuantumExperiment:
    best = (
        QuantumSampleResult(
            bitstring="01",
            count=10,
            probability=1.0,
            feasible=True,
            raw_mission_value=10.0,
            objective_value=10.0,
            qubo_energy=-10.0,
            violations_count=0,
        )
        if with_best
        else None
    )
    return QuantumExperiment(
        problem_checksum="x",
        status=status,
        configuration=SolverConfiguration(solver_kind=SolverKind.QUANTUM_QAOA),
        best_feasible_sample=best,
        feasible_sample_ratio=1.0,
    )


@pytest.mark.parametrize(
    "status",
    [
        ExperimentStatus.TIMED_OUT,
        ExperimentStatus.CANCELLED,
        ExperimentStatus.FAILED,
        ExperimentStatus.UNSUPPORTED,
        ExperimentStatus.PENDING,
        ExperimentStatus.RUNNING,
        ExperimentStatus.INCONCLUSIVE,
    ],
)
def test_non_completed_quantum_never_positive(status: ExperimentStatus) -> None:
    # Even WITH a (spurious) best feasible sample matching the optimum, a non-completed
    # quantum run must never receive a positive conclusion.
    conclusion, _ = conclude(
        exact_result=_exact(10.0),
        greedy_result=None,
        quantum_experiment=_quantum(status, with_best=True),
        thresholds=BenchmarkThresholds(),
    )
    assert conclusion not in (
        ComparisonConclusion.QUANTUM_COMPETITIVE,
        ComparisonConclusion.EQUIVALENT_OBJECTIVE,
    )


def test_different_problem_checksum_is_non_positive() -> None:
    q = _quantum(ExperimentStatus.COMPLETED).model_copy(update={"problem_checksum": "OTHER"})
    conclusion, _ = conclude(
        exact_result=_exact(10.0),
        greedy_result=None,
        quantum_experiment=q,
        thresholds=BenchmarkThresholds(),
    )
    assert conclusion == ComparisonConclusion.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# #2 verification tamper-resistance
# ---------------------------------------------------------------------------
def _fast_run(name: str = "default"):
    problem = normalize_problem(fixtures.fixture(name))
    run = run_benchmark(problem, seed=7, run_quantum=False)
    return problem, run


def test_clean_classical_benchmark_verifies() -> None:
    problem, run = _fast_run()
    assert all_critical_passed(verify_benchmark(problem, run))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.model_copy(update={"problem_checksum": "deadbeef"}),
        lambda r: r.model_copy(
            update={
                "solver_results": [
                    r.solver_results[0].model_copy(update={"objective_value": 999.0}),
                    r.solver_results[1],
                ]
            }
        ),
        lambda r: r.model_copy(
            update={
                "solver_results": [
                    r.solver_results[0].model_copy(
                        update={"optimality_status": OptimalityStatus.FEASIBLE}
                    ),
                    r.solver_results[1],
                ]
            }
        ),
        lambda r: r.model_copy(
            update={
                "comparison": r.comparison.model_copy(
                    update={"conclusion": ComparisonConclusion.QUANTUM_COMPETITIVE}
                )
            }
        ),
        lambda r: r.model_copy(
            update={"comparison": r.comparison.model_copy(update={"exact_objective": 123.0})}
        ),
        lambda r: r.model_copy(
            update={"comparison": r.comparison.model_copy(update={"known_optimum": 123.0})}
        ),
    ],
)
def test_classical_tamper_is_rejected(mutate) -> None:
    problem, run = _fast_run()
    tampered = mutate(run)
    assert not all_critical_passed(verify_benchmark(problem, tampered))


def test_tampered_selected_schedule_rejected() -> None:
    problem, run = _fast_run()
    exact = run.solver_results[0]
    bad_schedule = exact.schedule.model_copy(
        update={"selected_opportunity_ids": ("OPP-1", "OPP-2")}
    )
    bad_exact = exact.model_copy(update={"schedule": bad_schedule})
    tampered = run.model_copy(update={"solver_results": [bad_exact, run.solver_results[1]]})
    assert not all_critical_passed(verify_benchmark(problem, tampered))


# Quantum tamper tests run the benchmark with quantum ONCE (isolated subprocess).
@pytest.fixture(scope="module")
def quantum_run():
    problem = normalize_problem(fixtures.fixture("default"))
    run = run_benchmark(problem, seed=7, shots=1024, optimizer_iterations=16, run_quantum=True)
    return problem, run


def test_quantum_clean_verifies(quantum_run) -> None:
    problem, run = quantum_run
    if run.quantum_experiment.status != ExperimentStatus.COMPLETED:
        pytest.skip("quantum did not complete in this environment")
    assert all_critical_passed(verify_benchmark(problem, run))


@pytest.mark.parametrize(
    "field,value",
    [
        ("total_shots", 999999),
        ("feasible_sample_ratio", 0.123),
        ("distinct_samples", 999),
        ("exact_optimum_in_samples", False),
        ("objective_gap", 42.0),
    ],
)
def test_quantum_scalar_tamper_rejected(quantum_run, field, value) -> None:
    problem, run = quantum_run
    if run.quantum_experiment.status != ExperimentStatus.COMPLETED:
        pytest.skip("quantum did not complete")
    qe = run.quantum_experiment.model_copy(update={field: value})
    tampered = run.model_copy(update={"quantum_experiment": qe})
    assert not all_critical_passed(verify_benchmark(problem, tampered))


def test_quantum_sample_and_seed_and_backend_tamper_rejected(quantum_run) -> None:
    problem, run = quantum_run
    qe = run.quantum_experiment
    if qe.status != ExperimentStatus.COMPLETED:
        pytest.skip("quantum did not complete")
    # Tamper a sample count.
    s0 = qe.samples[0].model_copy(update={"count": qe.samples[0].count + 5000})
    bad_samples = qe.model_copy(update={"samples": [s0, *qe.samples[1:]]})
    assert not all_critical_passed(
        verify_benchmark(problem, run.model_copy(update={"quantum_experiment": bad_samples}))
    )
    # Tamper a sample probability.
    sp = qe.samples[0].model_copy(update={"probability": 0.999})
    bad_prob = qe.model_copy(update={"samples": [sp, *qe.samples[1:]]})
    assert not all_critical_passed(
        verify_benchmark(problem, run.model_copy(update={"quantum_experiment": bad_prob}))
    )
    # Tamper a sample qubo energy.
    se = qe.samples[0].model_copy(update={"qubo_energy": qe.samples[0].qubo_energy + 10.0})
    bad_energy = qe.model_copy(update={"samples": [se, *qe.samples[1:]]})
    assert not all_critical_passed(
        verify_benchmark(problem, run.model_copy(update={"quantum_experiment": bad_energy}))
    )
    # Tamper the simulator seed.
    bad_seed = qe.model_copy(
        update={"circuit_metadata": qe.circuit_metadata.model_copy(update={"seed_simulator": 999})}
    )
    assert not all_critical_passed(
        verify_benchmark(problem, run.model_copy(update={"quantum_experiment": bad_seed}))
    )
    # Tamper the simulator backend (claim non-Aer).
    bad_backend = qe.model_copy(
        update={
            "circuit_metadata": qe.circuit_metadata.model_copy(
                update={"simulator_backend": "ibm_real_hw"}
            )
        }
    )
    assert not all_critical_passed(
        verify_benchmark(problem, run.model_copy(update={"quantum_experiment": bad_backend}))
    )


def test_selected_sample_not_observed_rejected(quantum_run) -> None:
    problem, run = quantum_run
    qe = run.quantum_experiment
    if qe.status != ExperimentStatus.COMPLETED or qe.best_feasible_sample is None:
        pytest.skip("quantum did not complete")
    fake = qe.best_feasible_sample.model_copy(
        update={"bitstring": "1111"}
    )  # not in observed samples
    bad = qe.model_copy(update={"best_feasible_sample": fake})
    assert not all_critical_passed(
        verify_benchmark(problem, run.model_copy(update={"quantum_experiment": bad}))
    )


# ---------------------------------------------------------------------------
# #2 artifact tamper (checksum + path containment)
# ---------------------------------------------------------------------------
def test_artifact_checksum_and_path_tamper_rejected() -> None:
    from orbitmind.visualization.optimization_charts import OptimizationVisualizationService

    problem, run = _fast_run()
    root = Path(tempfile.mkdtemp())
    viz = OptimizationVisualizationService(root)
    findings = verify_benchmark(problem, run)
    artifacts = viz.generate(problem, run, findings, seed=7)
    run = run.model_copy(update={"artifacts": artifacts})
    assert all_critical_passed(verify_benchmark(problem, run, artifacts_root=root))

    # Tamper an artifact checksum.
    bad_art = [{**artifacts[0], "checksum": "0" * 64}, *artifacts[1:]]
    bad_run = run.model_copy(update={"artifacts": bad_art})
    assert not all_critical_passed(verify_benchmark(problem, bad_run, artifacts_root=root))

    # Tamper an artifact path to escape the artifacts root.
    esc = [{**artifacts[0], "path": "../escape.png"}, *artifacts[1:]]
    esc_run = run.model_copy(update={"artifacts": esc})
    assert not all_critical_passed(verify_benchmark(problem, esc_run, artifacts_root=root))
