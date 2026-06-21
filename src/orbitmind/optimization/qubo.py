"""Manually controlled QUBO encoding for bounded scheduling (no qiskit-optimization).

The QUBO minimizes ``E(x) = offset + sum_i linear_i x_i + sum_{i<j} quad_ij x_i x_j`` and
is constructed so that ``E(x) == -penalized_objective(x)`` for the shared Evaluator. This
identity is exhaustively verified on tiny instances (a mismatch is a critical failure).

Encoded penalties (all exactly linear/quadratic in x, no slack variables):
- pairwise conflicts (same-satellite overlap + mutual exclusion): +P when both selected
- mandatory opportunity m: +P when NOT selected, i.e. +P(1 - x_m)
Resource/cardinality constraints (capacity, max-observations, per-target, min-value) are
enforced by the independent Evaluator (feasibility), not folded into the QUBO energy.
"""

from __future__ import annotations

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.optimization.models import QuboModel, SchedulingProblem
from orbitmind.optimization.problem import (
    generate_conflicts,
    resolved_penalty,
    variable_order,
)


def build_qubo(problem: SchedulingProblem) -> QuboModel:
    order = variable_order(problem)
    index = {opp_id: i for i, opp_id in enumerate(order)}
    penalty = resolved_penalty(problem)
    weight = problem.objective.mission_value_weight
    value = {opp.id: opp.mission_value * weight for opp in problem.opportunities}  # weighted
    mandatory = set(problem.constraints.mandatory)
    conflicts = generate_conflicts(problem)

    linear: dict[int, float] = {}
    quadratic: dict[str, float] = {}

    # E(x) = -penalized_objective(x), with weighted mission value:
    #   linear_i  = -(value_i * weight) - P*[i in mandatory]
    #   quad_ij   = +P  for each conflict pair
    #   offset    = +P * |mandatory|
    for opp_id, i in index.items():
        coeff = -value[opp_id]
        if opp_id in mandatory:
            coeff -= penalty
        if coeff != 0.0:
            linear[i] = coeff
    for conflict in conflicts:
        i, j = index[conflict.opportunity_a], index[conflict.opportunity_b]
        a, b = (i, j) if i < j else (j, i)
        key = f"{a},{b}"
        quadratic[key] = quadratic.get(key, 0.0) + penalty

    offset = penalty * len(mandatory)
    explanation = (
        f"penalty P={penalty}: +P per conflict pair both-selected ({len(conflicts)} pairs), "
        f"+P(1-x_m) per mandatory opportunity ({len(mandatory)}). "
        "Capacity/cardinality enforced by the independent evaluator."
    )
    qubo = QuboModel(
        num_vars=len(order),
        variable_opportunities=order,
        linear=linear,
        quadratic=quadratic,
        offset=offset,
        penalty_coefficient=penalty,
        penalty_explanation=explanation,
    )
    return qubo.model_copy(update={"checksum": _qubo_checksum(qubo)})


def _qubo_checksum(qubo: QuboModel) -> str:
    return sha256_canonical_json(
        {
            "num_vars": qubo.num_vars,
            "variables": list(qubo.variable_opportunities),
            "linear": {str(k): qubo.linear[k] for k in sorted(qubo.linear)},
            "quadratic": {k: qubo.quadratic[k] for k in sorted(qubo.quadratic)},
            "offset": qubo.offset,
            "penalty": qubo.penalty_coefficient,
        }
    )


def qubo_energy(qubo: QuboModel, bits: str) -> float:
    """Energy of an assignment. ``bits[i]`` is variable ``i`` in variable order."""
    if len(bits) != qubo.num_vars:
        raise ValueError(f"bitstring length {len(bits)} != num vars {qubo.num_vars}")
    x = [1 if b == "1" else 0 for b in bits]
    energy = qubo.offset
    for i, coeff in qubo.linear.items():
        energy += coeff * x[i]
    for key, coeff in qubo.quadratic.items():
        a, b = key.split(",")
        energy += coeff * x[int(a)] * x[int(b)]
    return energy


def qubo_to_ising(qubo: QuboModel) -> tuple[dict[int, float], dict[tuple[int, int], float], float]:
    """Convert QUBO (x in {0,1}) to Ising (z in {-1,+1}) via x = (1 - z)/2.

    Returns (h, J, offset) for H = sum_i h_i Z_i + sum_{i<j} J_ij Z_i Z_j + offset.
    """
    h: dict[int, float] = dict.fromkeys(range(qubo.num_vars), 0.0)
    j_coeffs: dict[tuple[int, int], float] = {}
    offset = qubo.offset

    for i, a in qubo.linear.items():
        offset += a / 2.0
        h[i] = h.get(i, 0.0) - a / 2.0
    for key, b in qubo.quadratic.items():
        si, sj = key.split(",")
        i, j = int(si), int(sj)
        offset += b / 4.0
        h[i] = h.get(i, 0.0) - b / 4.0
        h[j] = h.get(j, 0.0) - b / 4.0
        j_coeffs[(i, j)] = j_coeffs.get((i, j), 0.0) + b / 4.0

    h = {i: c for i, c in h.items() if abs(c) > 1e-12}
    j_coeffs = {k: c for k, c in j_coeffs.items() if abs(c) > 1e-12}
    return h, j_coeffs, offset
