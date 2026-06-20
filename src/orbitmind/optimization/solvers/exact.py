"""Exact solver: deterministic exhaustive search (ground truth for tiny instances)."""

from __future__ import annotations

import time

from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    SchedulingProblem,
    SolverConfiguration,
    SolverResult,
)
from orbitmind.optimization.solvers.base import build_result

_NAME = "exhaustive-exact"
_VERSION = "1.0"
_LIMITS = (
    "Exhaustive over 2^n subsets; the proven optimum ONLY for instances small enough to "
    "enumerate (n <= exact_max_variables). Not a scalable solver."
)


def solve_exact(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
) -> SolverResult:
    """Enumerate all subsets; return the best independently-verified feasible schedule."""
    evaluator = evaluator or Evaluator(problem)
    order = evaluator.order
    n = len(order)

    if n > problem.limits.exact_max_variables:
        return build_result(
            solver_kind=config.solver_kind,
            solver_name=_NAME,
            solver_version=_VERSION,
            problem_checksum=problem.checksum,
            config=config,
            evaluation=None,
            status=ExperimentStatus.UNSUPPORTED,
            optimality=OptimalityStatus.UNKNOWN,
            known_optimum=None,
            runtime_seconds=0.0,
            evaluated_candidates=0,
            limitations=_LIMITS,
            error=f"n={n} exceeds exact_max_variables={problem.limits.exact_max_variables}",
        )

    start = time.perf_counter()
    deadline = start + config.timeout_seconds
    best_eval = None
    best_obj = float("-inf")
    evaluated = 0
    timed_out = False

    for mask in range(1 << n):
        if (mask & 0x3FF) == 0 and time.perf_counter() > deadline:
            timed_out = True
            break
        selected = {order[i] for i in range(n) if (mask >> i) & 1}
        ev = evaluator.evaluate(selected)
        evaluated += 1
        if ev.feasible and ev.objective_value > best_obj:
            best_obj = ev.objective_value
            best_eval = ev

    runtime = time.perf_counter() - start
    if best_eval is None:
        status = ExperimentStatus.TIMED_OUT if timed_out else ExperimentStatus.COMPLETED
        return build_result(
            solver_kind=config.solver_kind,
            solver_name=_NAME,
            solver_version=_VERSION,
            problem_checksum=problem.checksum,
            config=config,
            evaluation=None,
            status=status,
            optimality=OptimalityStatus.INFEASIBLE,
            known_optimum=None,
            runtime_seconds=runtime,
            evaluated_candidates=evaluated,
            limitations=_LIMITS,
        )
    optimality = OptimalityStatus.FEASIBLE if timed_out else OptimalityStatus.OPTIMAL
    status = ExperimentStatus.TIMED_OUT if timed_out else ExperimentStatus.COMPLETED
    known_optimum = None if timed_out else best_eval.objective_value
    return build_result(
        solver_kind=config.solver_kind,
        solver_name=_NAME,
        solver_version=_VERSION,
        problem_checksum=problem.checksum,
        config=config,
        evaluation=best_eval,
        status=status,
        optimality=optimality,
        known_optimum=known_optimum,
        runtime_seconds=runtime,
        evaluated_candidates=evaluated,
        limitations=_LIMITS,
    )
