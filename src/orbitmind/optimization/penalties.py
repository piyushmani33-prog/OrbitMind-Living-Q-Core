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

from orbitmind.core.errors import ValidationError
from orbitmind.optimization.models import (
    PenaltyProofStatus,
    SchedulingConflict,
    SchedulingProblem,
)
from orbitmind.optimization.problem import (
    generate_conflicts,
    resolved_penalty,
    total_weighted_value_bound,
    variable_order,
)

_EXHAUSTIVE_MAX_VARS = 16

# Proof statuses under which the QUBO is safe to execute on Aer (review finding #13).
_EXECUTABLE_PROOF = frozenset(
    {PenaltyProofStatus.PROVEN_SUFFICIENT, PenaltyProofStatus.NOT_APPLICABLE}
)


class PenaltyPolicy(BaseModel):
    """Auditable record of the penalty policy + its sufficiency proof."""

    penalty: float
    source: str  # "auto-weighted-bound" | "explicit"
    total_weighted_value_bound: float
    bound_formula: str
    satisfying_encoded_assignment_exists: bool
    sufficient: bool
    method: str  # "exhaustive" | "analytical-bound" | "analytic-satisfiability"
    proof_status: PenaltyProofStatus = PenaltyProofStatus.UNPROVEN


def encoded_constraints_satisfiable(problem: SchedulingProblem) -> bool:
    """Analytic satisfiability of the ENCODED hard constraints, for ALL sizes (finding #12).

    The only encoded hard constraints are: (a) every mandatory variable selected, and (b) no
    conflict pair both-selected. The candidate "select exactly the mandatory set" satisfies
    (a) trivially and violates (b) iff a conflict edge joins two mandatory variables. Any
    zero-violation assignment must select all mandatory, so such an edge makes the encoded
    constraints contradictory regardless of the other variables. O(conflicts), no enumeration.
    """
    mandatory = set(problem.constraints.mandatory)
    return not any(
        c.opportunity_a in mandatory and c.opportunity_b in mandatory
        for c in generate_conflicts(problem)
    )


def proof_allows_execution(status: PenaltyProofStatus) -> bool:
    """The QUBO may run on Aer only under an executable proof status (finding #13)."""
    return status in _EXECUTABLE_PROOF


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
    """Compute the penalty + assign an explicit proof status. Never raises for proof.

    Order of decisions (review findings #11/#12/#13):
      1. No encoded constraints at all          -> NOT_APPLICABLE (penalty plays no role).
      2. Encoded hard constraints unsatisfiable  -> CONTRADICTORY (never 'sufficient').
      3. Penalty zero/negative/NaN/inf           -> PROVEN_UNSAFE.
      4. Tiny instance (n<=16)                    -> exhaustive proof (PROVEN_SUFFICIENT/UNSAFE).
      5. Larger instance, P > bound               -> PROVEN_SUFFICIENT (analytic bound proof).
      6. Larger instance, P <= bound              -> UNPROVEN (cannot prove cheaply).
    """
    bound = total_weighted_value_bound(problem)
    source = (
        "explicit" if problem.objective.penalty_coefficient is not None else "auto-weighted-bound"
    )
    order = variable_order(problem)
    n = len(order)
    index = {opp_id: i for i, opp_id in enumerate(order)}
    conflicts = generate_conflicts(problem)
    mandatory = set(problem.constraints.mandatory)

    # Resolve the penalty defensively: an invalid explicit penalty is PROVEN_UNSAFE, not a raise.
    try:
        penalty = resolved_penalty(problem)
        penalty_valid = math.isfinite(penalty) and penalty > 0.0
    except ValidationError:
        penalty = problem.objective.penalty_coefficient or float("nan")
        penalty_valid = False

    has_encoded = bool(conflicts) or bool(mandatory)
    satisfiable = encoded_constraints_satisfiable(problem)

    method = "analytic-satisfiability"
    if not has_encoded:
        status = PenaltyProofStatus.NOT_APPLICABLE
        exists, sufficient = True, True
    elif not satisfiable:
        status = PenaltyProofStatus.CONTRADICTORY
        exists, sufficient = False, False
    elif not penalty_valid:
        status = PenaltyProofStatus.PROVEN_UNSAFE
        exists, sufficient = True, False
    elif n <= _EXHAUSTIVE_MAX_VARS:
        # Exhaustive proof: the global QUBO minimum must be an encoded-feasible assignment,
        # strictly below every encoded-infeasible one.
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
        status = (
            PenaltyProofStatus.PROVEN_SUFFICIENT if sufficient else PenaltyProofStatus.PROVEN_UNSAFE
        )
        method = "exhaustive"
    elif penalty > bound:
        status = PenaltyProofStatus.PROVEN_SUFFICIENT  # analytic: P strictly exceeds the bound
        exists, sufficient = True, True
        method = "analytical-bound"
    else:
        status = PenaltyProofStatus.UNPROVEN  # large custom penalty, no cheap proof
        exists, sufficient = True, False
        method = "analytical-bound"

    return PenaltyPolicy(
        penalty=penalty,
        source=source,
        total_weighted_value_bound=bound,
        bound_formula="P > sum(max(0, mission_value) * mission_value_weight)",
        satisfying_encoded_assignment_exists=exists,
        sufficient=sufficient,
        method=method,
        proof_status=status,
    )


def penalty_is_sufficient(problem: SchedulingProblem) -> bool:
    """True iff the penalty provably never lets an encoded violation be optimal."""
    return penalty_policy(problem).sufficient
