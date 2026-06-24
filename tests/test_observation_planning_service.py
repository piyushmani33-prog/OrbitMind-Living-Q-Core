"""Phase 4B.1 tests: in-memory authoritative classical observation planning."""

from __future__ import annotations

import builtins
import datetime as dt
from typing import Any

import pytest

from orbitmind.observation_planning import (
    AuthoritativePlanningSolver,
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    PlanningOptimalityLabel,
    PlanningResultStatus,
    PlanningVerificationLabel,
    plan_observation_request,
)
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ConstraintSet,
    ExperimentStatus,
    ObservationOpportunity,
    ObservationTarget,
    OptimalityStatus,
    SatelliteResource,
    SchedulingProblem,
    SchedulingProblemLimits,
    SolverConfiguration,
    SolverKind,
    SolverResult,
    TimeWindow,
)
from orbitmind.optimization.solvers.base import build_result


def _horizon() -> PlanningHorizon:
    return PlanningHorizon(
        start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
    )


def _opp(
    oid: str,
    *,
    sat: str = "SAT-A",
    target: str = "T1",
    start_min: int = 0,
    end_min: int = 30,
    value: float = 5.0,
    energy: float = 1.0,
    storage: float = 1.0,
) -> ObservationOpportunity:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationOpportunity(
        id=oid,
        satellite_id=sat,
        target_id=target,
        window=TimeWindow(
            start=base + dt.timedelta(minutes=start_min),
            end=base + dt.timedelta(minutes=end_min),
        ),
        mission_value=value,
        duration_seconds=(end_min - start_min) * 60.0,
        energy_cost=energy,
        storage_cost=storage,
    )


def _declared_request(
    *,
    opportunities: tuple[ObservationOpportunity, ...] | None = None,
    constraints: ConstraintSet | None = None,
    limits: SchedulingProblemLimits | None = None,
    satellites: tuple[SatelliteResource, ...] | None = None,
    targets: tuple[ObservationTarget, ...] | None = None,
) -> ObservationPlanningRequest:
    return ObservationPlanningRequest(
        name="declared service planning prototype",
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=opportunities or (_opp("OPP-A"),),
        satellites=satellites
        or (SatelliteResource(id="SAT-A", energy_capacity=10.0, storage_capacity=10.0),),
        targets=targets or (ObservationTarget(id="T1"),),
        constraints=constraints or ConstraintSet(),
        limits=limits or SchedulingProblemLimits(),
    )


def _scientific_identity(result: object) -> tuple[object, ...]:
    planning = result
    assert hasattr(planning, "schedule")
    schedule = planning.schedule
    evaluation = planning.independent_evaluation
    return (
        planning.request_checksum,
        planning.problem_checksum,
        planning.source_mode,
        planning.selected_solver,
        planning.status,
        planning.optimality_label,
        schedule.selected_opportunity_ids if schedule else None,
        evaluation.objective_value if evaluation else None,
        evaluation.feasible if evaluation else None,
        planning.verification_label,
    )


def _fake_exact_with_status(
    status: ExperimentStatus,
    optimality: OptimalityStatus,
    *,
    selected: set[str] | None = None,
) -> object:
    def solver(
        problem: SchedulingProblem,
        config: SolverConfiguration,
        evaluator: Evaluator | None = None,
    ) -> SolverResult:
        ev = (evaluator or Evaluator(problem)).evaluate(selected or set())
        return build_result(
            solver_kind=SolverKind.EXACT,
            solver_name="fake-exact",
            solver_version="test",
            problem_checksum=problem.checksum,
            config=config,
            evaluation=ev,
            status=status,
            optimality=optimality,
            known_optimum=None,
            runtime_seconds=0.0,
            evaluated_candidates=1,
            limitations="test fake exact",
        )

    return solver


def test_fixture_request_produces_verified_classical_result() -> None:
    result = plan_observation_request(
        ObservationPlanningRequest(name="fixture plan", horizon=_horizon(), fixture_name="default")
    )

    assert result.status == PlanningResultStatus.VERIFIED_FEASIBLE
    assert result.selected_solver == AuthoritativePlanningSolver.EXACT
    assert result.optimality_label == PlanningOptimalityLabel.OPTIMAL
    assert result.verification_label == PlanningVerificationLabel.VERIFIED_FIXTURE_PLAN
    assert result.feasible is True
    assert result.independent_evaluation is not None
    assert "access-window geometry is not computed" in " ".join(result.limitations)


def test_declared_request_produces_verified_classical_result() -> None:
    result = plan_observation_request(_declared_request())

    assert result.status == PlanningResultStatus.VERIFIED_FEASIBLE
    assert result.verification_label == PlanningVerificationLabel.VERIFIED_DECLARED_OPPORTUNITY_PLAN
    assert result.source_mode == ObservationPlanningSourceMode.DECLARED
    assert result.independent_evaluation is not None
    assert result.independent_evaluation.feasible is True


def test_exact_solver_selected_within_supported_limit() -> None:
    result = plan_observation_request(_declared_request())

    assert result.selected_solver == AuthoritativePlanningSolver.EXACT
    assert result.optimality_label == PlanningOptimalityLabel.OPTIMAL


def test_greedy_selected_above_exact_limit_within_request_limit() -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30, value=5.0),
            _opp("OPP-B", start_min=40, end_min=70, value=6.0),
        ),
        limits=SchedulingProblemLimits(max_variables=2, exact_max_variables=1),
    )

    result = plan_observation_request(request)

    assert result.selected_solver == AuthoritativePlanningSolver.GREEDY
    assert result.status == PlanningResultStatus.VERIFIED_FEASIBLE
    assert result.optimality_label == PlanningOptimalityLabel.HEURISTIC


def test_exact_timeout_is_preserved_and_greedy_fallback_is_heuristic() -> None:
    result = plan_observation_request(
        _declared_request(),
        exact_solver=_fake_exact_with_status(
            ExperimentStatus.TIMED_OUT, OptimalityStatus.FEASIBLE, selected={"OPP-A"}
        ),
    )

    assert result.selected_solver == AuthoritativePlanningSolver.GREEDY
    assert result.status == PlanningResultStatus.VERIFIED_FEASIBLE
    assert result.optimality_label == PlanningOptimalityLabel.HEURISTIC
    assert len(result.fallback_history) == 1
    assert result.fallback_history[0].status == ExperimentStatus.TIMED_OUT


def test_exact_unsupported_result_is_preserved_in_fallback_history() -> None:
    result = plan_observation_request(
        _declared_request(),
        exact_solver=_fake_exact_with_status(
            ExperimentStatus.UNSUPPORTED, OptimalityStatus.UNKNOWN, selected=set()
        ),
    )

    assert result.selected_solver == AuthoritativePlanningSolver.GREEDY
    assert result.fallback_history[0].status == ExperimentStatus.UNSUPPORTED
    assert result.optimality_label == PlanningOptimalityLabel.HEURISTIC


def test_same_request_produces_identical_scientific_result_twice() -> None:
    request = _declared_request()

    first = plan_observation_request(request)
    second = plan_observation_request(request)

    assert _scientific_identity(first) == _scientific_identity(second)


def test_returned_schedule_independently_evaluates_as_feasible() -> None:
    result = plan_observation_request(_declared_request())

    assert result.schedule is not None
    assert result.independent_evaluation is not None
    assert result.independent_evaluation.selected_opportunity_ids == (
        result.schedule.selected_opportunity_ids
    )
    assert result.independent_evaluation.feasible is True


def test_solver_objective_matches_independently_recomputed_objective() -> None:
    result = plan_observation_request(_declared_request())

    assert result.authoritative_result is not None
    assert result.independent_evaluation is not None
    assert result.authoritative_result.objective_value == pytest.approx(
        result.independent_evaluation.objective_value
    )
    assert result.objective_value == pytest.approx(result.independent_evaluation.objective_value)


def test_mandatory_constraints_are_respected() -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30, value=1.0),
            _opp("OPP-B", start_min=40, end_min=70, value=10.0),
        ),
        constraints=ConstraintSet(mandatory=("OPP-A",)),
    )

    result = plan_observation_request(request)

    assert result.schedule is not None
    assert "OPP-A" in result.schedule.selected_opportunity_ids
    assert result.feasible is True


def test_mutually_exclusive_constraints_are_respected() -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30, value=10.0),
            _opp("OPP-B", start_min=40, end_min=70, value=9.0),
        ),
        constraints=ConstraintSet(mutually_exclusive=(("OPP-A", "OPP-B"),)),
    )

    result = plan_observation_request(request)

    assert result.schedule is not None
    selected = set(result.schedule.selected_opportunity_ids)
    assert not {"OPP-A", "OPP-B"}.issubset(selected)
    assert result.feasible is True


def test_infeasible_problem_produces_typed_non_success_result() -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=60),
            _opp("OPP-B", start_min=30, end_min=90),
        ),
        constraints=ConstraintSet(mandatory=("OPP-A", "OPP-B")),
    )

    result = plan_observation_request(request)

    assert result.status == PlanningResultStatus.INFEASIBLE
    assert result.optimality_label == PlanningOptimalityLabel.INFEASIBLE
    assert result.feasible is False
    assert result.independent_evaluation is None


def test_invalid_translation_does_not_execute_solver() -> None:
    calls: list[str] = []

    def solver(
        problem: SchedulingProblem,
        config: SolverConfiguration,
        evaluator: Evaluator | None = None,
    ) -> SolverResult:
        calls.append(problem.checksum)
        raise AssertionError("solver should not execute")

    request = _declared_request(
        opportunities=(_opp("OPP-A", sat="UNKNOWN"),),
    )

    result = plan_observation_request(request, exact_solver=solver, greedy_solver=solver)

    assert result.status == PlanningResultStatus.INVALID
    assert calls == []


def test_request_is_not_mutated() -> None:
    offset = dt.timezone(dt.timedelta(hours=5))
    start = dt.datetime(2026, 6, 21, 15, 0, tzinfo=offset)
    request = _declared_request(
        opportunities=(
            _opp("OPP-A").model_copy(
                update={
                    "window": TimeWindow(
                        start=start,
                        end=start + dt.timedelta(minutes=30),
                    )
                }
            ),
        )
    )
    before = request.model_dump(mode="json")

    plan_observation_request(request)

    assert request.model_dump(mode="json") == before
    assert request.opportunities[0].window.start.tzinfo == offset


def test_no_quantum_adapter_or_qaoa_path_is_invoked(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.startswith("orbitmind.quantum") or name.startswith(
            "orbitmind.optimization.quantum"
        ):
            raise AssertionError(f"quantum import attempted: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    result = plan_observation_request(_declared_request())

    assert result.status == PlanningResultStatus.VERIFIED_FEASIBLE


def test_fixture_and_declared_labels_remain_distinct() -> None:
    fixture = plan_observation_request(
        ObservationPlanningRequest(name="fixture", horizon=_horizon(), fixture_name="default")
    )
    declared = plan_observation_request(_declared_request())

    assert fixture.verification_label == PlanningVerificationLabel.VERIFIED_FIXTURE_PLAN
    assert (
        declared.verification_label == PlanningVerificationLabel.VERIFIED_DECLARED_OPPORTUNITY_PLAN
    )


def test_heuristic_output_is_never_labelled_optimal() -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30, value=5.0),
            _opp("OPP-B", start_min=40, end_min=70, value=6.0),
        ),
        limits=SchedulingProblemLimits(max_variables=2, exact_max_variables=1),
    )

    result = plan_observation_request(request)

    assert result.selected_solver == AuthoritativePlanningSolver.GREEDY
    assert result.optimality_label == PlanningOptimalityLabel.HEURISTIC
    assert result.optimality_label != PlanningOptimalityLabel.OPTIMAL


def test_unexpected_exact_failure_is_not_converted_to_greedy_success() -> None:
    greedy_calls: list[str] = []

    def failing_exact(
        problem: SchedulingProblem,
        config: SolverConfiguration,
        evaluator: Evaluator | None = None,
    ) -> SolverResult:
        raise RuntimeError("unexpected exact failure")

    def greedy(
        problem: SchedulingProblem,
        config: SolverConfiguration,
        evaluator: Evaluator | None = None,
    ) -> SolverResult:
        greedy_calls.append(problem.checksum)
        raise AssertionError("greedy fallback should not run")

    with pytest.raises(RuntimeError, match="unexpected exact failure"):
        plan_observation_request(
            _declared_request(),
            exact_solver=failing_exact,
            greedy_solver=greedy,
        )

    assert greedy_calls == []
