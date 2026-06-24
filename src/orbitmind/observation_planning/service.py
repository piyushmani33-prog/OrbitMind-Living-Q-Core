"""In-memory authoritative classical planning service for Phase 4B.1."""

from __future__ import annotations

import math
from collections.abc import Callable

from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning.models import (
    AuthoritativePlanningSolver,
    ObservationPlanningRequest,
    ObservationPlanningResult,
    ObservationPlanningSourceMode,
    PlanningOptimalityLabel,
    PlanningResultStatus,
    RequestToProblemTranslation,
    planning_request_checksum,
    translate_request_to_problem,
)
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    ScheduleEvaluation,
    SchedulingProblem,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.solvers import solve_exact, solve_greedy

SolverFn = Callable[[SchedulingProblem, SolverConfiguration, Evaluator | None], SolverResult]


def plan_observation_request(
    request: ObservationPlanningRequest,
    *,
    exact_solver: SolverFn = solve_exact,
    greedy_solver: SolverFn = solve_greedy,
    allow_greedy_fallback: bool = True,
) -> ObservationPlanningResult:
    """Translate a request and produce an in-memory authoritative classical plan."""

    try:
        translation = translate_request_to_problem(request)
    except ValidationError as exc:
        message = str(exc)
        return ObservationPlanningResult(
            request_checksum=planning_request_checksum(request),
            source_mode=request.source_mode,
            status=PlanningResultStatus.INVALID,
            optimality_label=PlanningOptimalityLabel.UNKNOWN,
            limitations=(message,),
            verification_errors=(message,),
        )

    problem = translation.problem
    evaluator = Evaluator(problem)
    exact_config = SolverConfiguration(
        solver_kind=SolverKind.EXACT,
        timeout_seconds=problem.limits.max_timeout_seconds,
    )
    greedy_config = SolverConfiguration(
        solver_kind=SolverKind.GREEDY,
        timeout_seconds=problem.limits.max_timeout_seconds,
    )

    if len(problem.opportunities) > problem.limits.exact_max_variables:
        greedy = greedy_solver(problem, greedy_config, evaluator)
        return _finalize_result(
            translation=translation,
            solver=AuthoritativePlanningSolver.GREEDY,
            solver_result=greedy,
            evaluator=evaluator,
            fallback_history=(),
        )

    exact = exact_solver(problem, exact_config, evaluator)
    if exact.status in {ExperimentStatus.TIMED_OUT, ExperimentStatus.UNSUPPORTED}:
        if allow_greedy_fallback:
            greedy = greedy_solver(problem, greedy_config, evaluator)
            return _finalize_result(
                translation=translation,
                solver=AuthoritativePlanningSolver.GREEDY,
                solver_result=greedy,
                evaluator=evaluator,
                fallback_history=(exact,),
                force_heuristic=True,
            )
        return _finalize_result(
            translation=translation,
            solver=AuthoritativePlanningSolver.EXACT,
            solver_result=exact,
            evaluator=evaluator,
            fallback_history=(),
        )

    return _finalize_result(
        translation=translation,
        solver=AuthoritativePlanningSolver.EXACT,
        solver_result=exact,
        evaluator=evaluator,
        fallback_history=(),
    )


def _finalize_result(
    *,
    translation: RequestToProblemTranslation,
    solver: AuthoritativePlanningSolver,
    solver_result: SolverResult,
    evaluator: Evaluator,
    fallback_history: tuple[SolverResult, ...],
    force_heuristic: bool = False,
) -> ObservationPlanningResult:
    problem = translation.problem
    independent_evaluation = None
    verification_errors: list[str] = []

    if solver_result.problem_checksum != problem.checksum:
        verification_errors.append("solver result problem checksum does not match translation")

    if solver_result.schedule is not None:
        independent_evaluation = evaluator.evaluate(
            set(solver_result.schedule.selected_opportunity_ids)
        )
        if independent_evaluation.problem_checksum != problem.checksum:
            verification_errors.append("independent evaluation problem checksum does not match")
        if (
            solver_result.objective_value is not None
            and independent_evaluation.feasible
            and not math.isclose(
                solver_result.objective_value,
                independent_evaluation.objective_value,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
        ):
            verification_errors.append("solver objective does not match independent evaluation")

    if verification_errors:
        return _build_planning_result(
            translation=translation,
            solver=solver,
            solver_result=solver_result,
            independent_evaluation=independent_evaluation,
            fallback_history=fallback_history,
            status=PlanningResultStatus.FAILED,
            optimality_label=PlanningOptimalityLabel.UNKNOWN,
            feasible=False,
            verification_errors=tuple(verification_errors),
        )

    status, optimality_label, feasible = _classify_result(
        solver=solver,
        solver_result=solver_result,
        independent_feasible=(
            independent_evaluation.feasible if independent_evaluation is not None else False
        ),
        force_heuristic=force_heuristic,
    )
    return _build_planning_result(
        translation=translation,
        solver=solver,
        solver_result=solver_result,
        independent_evaluation=independent_evaluation,
        fallback_history=fallback_history,
        status=status,
        optimality_label=optimality_label,
        feasible=feasible,
        verification_errors=(),
    )


def _classify_result(
    *,
    solver: AuthoritativePlanningSolver,
    solver_result: SolverResult,
    independent_feasible: bool,
    force_heuristic: bool,
) -> tuple[PlanningResultStatus, PlanningOptimalityLabel, bool]:
    if solver_result.status == ExperimentStatus.TIMED_OUT:
        return PlanningResultStatus.TIMED_OUT, PlanningOptimalityLabel.UNKNOWN, False
    if solver_result.status == ExperimentStatus.UNSUPPORTED:
        return PlanningResultStatus.UNSUPPORTED, PlanningOptimalityLabel.UNKNOWN, False
    if solver_result.status != ExperimentStatus.COMPLETED:
        return PlanningResultStatus.FAILED, PlanningOptimalityLabel.UNKNOWN, False
    if not independent_feasible:
        return PlanningResultStatus.INFEASIBLE, PlanningOptimalityLabel.INFEASIBLE, False
    if (
        solver == AuthoritativePlanningSolver.EXACT
        and solver_result.optimality_status == OptimalityStatus.OPTIMAL
        and not force_heuristic
    ):
        return PlanningResultStatus.VERIFIED_FEASIBLE, PlanningOptimalityLabel.OPTIMAL, True
    return PlanningResultStatus.VERIFIED_FEASIBLE, PlanningOptimalityLabel.HEURISTIC, True


def _build_planning_result(
    *,
    translation: RequestToProblemTranslation,
    solver: AuthoritativePlanningSolver,
    solver_result: SolverResult,
    independent_evaluation: ScheduleEvaluation | None,
    fallback_history: tuple[SolverResult, ...],
    status: PlanningResultStatus,
    optimality_label: PlanningOptimalityLabel,
    feasible: bool,
    verification_errors: tuple[str, ...],
) -> ObservationPlanningResult:
    objective = (
        independent_evaluation.objective_value if independent_evaluation is not None else None
    )
    return ObservationPlanningResult(
        request_checksum=translation.request_checksum,
        problem_checksum=translation.problem.checksum,
        source_mode=_translation_source_mode(translation),
        selected_solver=solver,
        solver_execution_status=solver_result.status,
        status=status,
        optimality_label=optimality_label,
        verification_label=translation.verification_label,
        limitations=tuple(
            item for item in (*translation.limitations, solver_result.limitations) if item
        ),
        schedule=solver_result.schedule,
        authoritative_result=solver_result,
        independent_evaluation=independent_evaluation,
        feasible=feasible,
        objective_value=objective,
        fallback_history=fallback_history,
        verification_errors=verification_errors,
    )


def _translation_source_mode(
    translation: RequestToProblemTranslation,
) -> ObservationPlanningSourceMode:
    if translation.problem.source == "observation-planning-declared":
        return ObservationPlanningSourceMode.DECLARED
    return ObservationPlanningSourceMode.FIXTURE
