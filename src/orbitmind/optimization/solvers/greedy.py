"""Greedy solver: deterministic heuristic with a documented ordering rule.

Ordering rule (fixed, no randomness): mandatory opportunities first, then by descending
value density (mission_value / duration_seconds), then descending mission_value, then
ascending opportunity id. An opportunity is added only if the resulting selection remains
feasible under the independent evaluator.
"""

from __future__ import annotations

import time

from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ExperimentStatus,
    ObservationOpportunity,
    OptimalityStatus,
    SchedulingProblem,
    SolverConfiguration,
    SolverResult,
)
from orbitmind.optimization.solvers.base import build_result

_NAME = "greedy-value-density"
_VERSION = "1.0"
_LIMITS = (
    "Deterministic greedy heuristic; not guaranteed optimal. Ordering: mandatory first, "
    "then value-density desc, value desc, id asc."
)


def _ordering_key(opp: ObservationOpportunity) -> tuple[float, float, str]:
    density = opp.mission_value / opp.duration_seconds if opp.duration_seconds else 0.0
    return (-density, -opp.mission_value, opp.id)


def solve_greedy(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
) -> SolverResult:
    evaluator = evaluator or Evaluator(problem)
    start = time.perf_counter()
    mandatory = set(problem.constraints.mandatory)
    evaluated = 0

    # The complete mandatory set is considered ATOMICALLY: seed the schedule with all of
    # it together (review finding #8). If the mandatory set itself is infeasible, return a
    # clearly-infeasible result rather than greedily testing each mandatory in isolation.
    selected: set[str] = set(mandatory)
    if mandatory:
        seed_eval = evaluator.evaluate(selected)
        evaluated += 1
        if not seed_eval.feasible:
            runtime = time.perf_counter() - start
            return build_result(
                solver_kind=config.solver_kind,
                solver_name=_NAME,
                solver_version=_VERSION,
                problem_checksum=problem.checksum,
                config=config,
                evaluation=seed_eval,
                status=ExperimentStatus.COMPLETED,
                optimality=OptimalityStatus.INFEASIBLE,
                known_optimum=None,
                runtime_seconds=runtime,
                evaluated_candidates=evaluated,
                limitations=_LIMITS + " (mandatory set is jointly infeasible)",
            )

    rest = sorted((o for o in problem.opportunities if o.id not in mandatory), key=_ordering_key)
    for opp in rest:
        candidate = selected | {opp.id}
        evaluated += 1
        if evaluator.evaluate(candidate).feasible:
            selected = candidate

    ev = evaluator.evaluate(selected)
    runtime = time.perf_counter() - start
    optimality = OptimalityStatus.FEASIBLE if ev.feasible else OptimalityStatus.INFEASIBLE
    return build_result(
        solver_kind=config.solver_kind,
        solver_name=_NAME,
        solver_version=_VERSION,
        problem_checksum=problem.checksum,
        config=config,
        evaluation=ev,
        status=ExperimentStatus.COMPLETED,
        optimality=optimality,
        known_optimum=None,
        runtime_seconds=runtime,
        evaluated_candidates=evaluated,
        limitations=_LIMITS,
    )
