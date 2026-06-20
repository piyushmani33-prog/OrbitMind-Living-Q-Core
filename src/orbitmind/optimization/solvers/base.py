"""Shared solver helpers: software-version capture and result assembly."""

from __future__ import annotations

import platform

from orbitmind import __version__
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    CandidateSchedule,
    ExperimentStatus,
    OptimalityStatus,
    ScheduleEvaluation,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)


def software_versions() -> dict[str, str]:
    return {"python": platform.python_version(), "orbitmind": __version__}


def build_result(
    *,
    solver_kind: SolverKind,
    solver_name: str,
    solver_version: str,
    problem_checksum: str,
    config: SolverConfiguration,
    evaluation: ScheduleEvaluation | None,
    status: ExperimentStatus,
    optimality: OptimalityStatus,
    known_optimum: float | None,
    runtime_seconds: float,
    evaluated_candidates: int,
    limitations: str,
    error: str = "",
) -> SolverResult:
    from orbitmind.optimization.models import ResourceUsage

    schedule: CandidateSchedule | None = None
    objective: float | None = None
    feasible = False
    if evaluation is not None:
        schedule = CandidateSchedule(
            problem_checksum=problem_checksum,
            selected_opportunity_ids=evaluation.selected_opportunity_ids,
            produced_by=solver_name,
        )
        objective = evaluation.objective_value
        feasible = evaluation.feasible
    gap = (
        known_optimum - objective
        if known_optimum is not None and objective is not None and feasible
        else None
    )
    return SolverResult(
        solver_kind=solver_kind,
        solver_name=solver_name,
        solver_version=solver_version,
        problem_checksum=problem_checksum,
        configuration=config,
        status=status,
        schedule=schedule,
        evaluation=evaluation,
        optimality_status=optimality,
        objective_value=objective,
        known_optimum=known_optimum,
        objective_gap=gap,
        feasible=feasible,
        seed=config.seed,
        runtime_seconds=runtime_seconds,
        resource_usage=ResourceUsage(
            evaluated_candidates=evaluated_candidates, wall_clock_seconds=runtime_seconds
        ),
        software_versions=software_versions(),
        limitations=limitations,
        error=error,
    )


def evaluator_for(problem: object) -> Evaluator:
    from orbitmind.optimization.models import SchedulingProblem

    assert isinstance(problem, SchedulingProblem)
    return Evaluator(problem)
