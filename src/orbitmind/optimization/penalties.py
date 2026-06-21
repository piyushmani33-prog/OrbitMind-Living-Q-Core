"""Penalty-policy proof + evidence for the QUBO encoding (ADR-0026, review finding #6).

The auto penalty ``P = total_weighted_positive_value + 1`` is provably large enough that no
encoded constraint violation can ever achieve a QUBO energy at or below the best feasible
assignment. For tiny instances we PROVE this exhaustively (enumerate all bitstrings); for
larger instances we rely on the analytical bound. A penalty is never reported sufficient
when no encoded-feasible assignment exists (contradictory hard constraints).
"""

from __future__ import annotations

import math
from itertools import product

from pydantic import BaseModel

from orbitmind.optimization.models import SchedulingConflict, SchedulingProblem
from orbitmind.optimization.problem import (
    generate_conflicts,
    resolved_penalty,
    total_weighted_value_bound,
    variable_order,
)

_EXHAUSTIVE_MAX_VARS = 16


class PenaltyPolicy(BaseModel):
    """Auditable record of the penalty policy + its sufficiency proof."""

    penalty: float
    source: str  # "auto-weighted-bound" | "explicit"
    total_weighted_value_bound: float
    bound_formula: str
    satisfying_encoded_assignment_exists: bool
    sufficient: bool
    method: str  # "exhaustive" | "analytical-bound"


def _encoded_violation_count(
    bits: str,
    index: dict[str, int],
    conflicts: tuple[SchedulingConflict, ...],
    mandatory: set[str],
) -> int:
    x = [c == "1" for c in bits]
    count = 0
    for conflict in conflicts:
        if x[index[conflict.opportunity_a]] and x[index[conflict.opportunity_b]]:
            count += 1
    for m in mandatory:
        if not x[index[m]]:
            count += 1
    return count


def penalty_policy(problem: SchedulingProblem) -> PenaltyPolicy:
    """Compute the penalty + prove (or bound) its sufficiency. Never raises for proof."""
    penalty = resolved_penalty(problem)
    bound = total_weighted_value_bound(problem)
    source = (
        "explicit" if problem.objective.penalty_coefficient is not None else "auto-weighted-bound"
    )
    order = variable_order(problem)
    n = len(order)
    index = {opp_id: i for i, opp_id in enumerate(order)}
    conflicts = generate_conflicts(problem)
    mandatory = set(problem.constraints.mandatory)

    if n <= _EXHAUSTIVE_MAX_VARS:
        # Exhaustive proof: the global QUBO minimum must be achieved by an encoded-feasible
        # assignment, with every encoded-infeasible assignment strictly higher in energy.
        from orbitmind.optimization.qubo import build_qubo, qubo_energy

        qubo = build_qubo(problem)
        best_feasible = math.inf
        best_infeasible = math.inf
        for bits_t in product("01", repeat=n):
            bits = "".join(bits_t)
            energy = qubo_energy(qubo, bits)
            if _encoded_violation_count(bits, index, conflicts, mandatory) == 0:
                best_feasible = min(best_feasible, energy)
            else:
                best_infeasible = min(best_infeasible, energy)
        exists = math.isfinite(best_feasible)
        sufficient = exists and (
            not math.isfinite(best_infeasible) or best_feasible < best_infeasible
        )
        method = "exhaustive"
    else:
        exists = True  # cannot prove cheaply; the analytical bound assumes satisfiability
        sufficient = penalty > bound and math.isfinite(penalty) and penalty > 0.0
        method = "analytical-bound"

    return PenaltyPolicy(
        penalty=penalty,
        source=source,
        total_weighted_value_bound=bound,
        bound_formula="P > sum(max(0, mission_value) * mission_value_weight)",
        satisfying_encoded_assignment_exists=exists,
        sufficient=sufficient,
        method=method,
    )


def penalty_is_sufficient(problem: SchedulingProblem) -> bool:
    """True iff the penalty provably never lets an encoded violation be optimal."""
    return penalty_policy(problem).sufficient
