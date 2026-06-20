"""Deterministic problem normalization, checksum, conflict generation, penalty sizing."""

from __future__ import annotations

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import ValidationError
from orbitmind.optimization.models import (
    ConstraintKind,
    SchedulingConflict,
    SchedulingProblem,
)


def variable_order(problem: SchedulingProblem) -> tuple[str, ...]:
    """Stable variable ordering: opportunity ids sorted lexicographically.

    The bit-order convention for every encoding/decoding is THIS order, index 0 first.
    """
    return tuple(sorted(opp.id for opp in problem.opportunities))


def _canonical(problem: SchedulingProblem) -> dict[str, object]:
    opps = sorted(problem.opportunities, key=lambda o: o.id)
    return {
        "name": problem.name,
        "opportunities": [
            {
                "id": o.id,
                "satellite_id": o.satellite_id,
                "target_id": o.target_id,
                "start": o.window.start.isoformat(),
                "end": o.window.end.isoformat(),
                "mission_value": o.mission_value,
                "duration_seconds": o.duration_seconds,
                "energy_cost": o.energy_cost,
                "storage_cost": o.storage_cost,
                "pointing_cost": o.pointing_cost,
                "priority": o.priority,
            }
            for o in opps
        ],
        "satellites": [
            {"id": s.id, "energy": s.energy_capacity, "storage": s.storage_capacity}
            for s in sorted(problem.satellites, key=lambda s: s.id)
        ],
        "targets": [
            {"id": t.id, "priority": t.priority}
            for t in sorted(problem.targets, key=lambda t: t.id)
        ],
        "constraints": {
            "max_observations": problem.constraints.max_observations,
            "mutually_exclusive": sorted(
                tuple(sorted(p)) for p in problem.constraints.mutually_exclusive
            ),
            "mandatory": sorted(problem.constraints.mandatory),
            "per_target_limit": problem.constraints.per_target_limit,
            "min_mission_value": problem.constraints.min_mission_value,
            "enforce_no_overlap": problem.constraints.enforce_no_overlap,
            "enforce_energy_capacity": problem.constraints.enforce_energy_capacity,
            "enforce_storage_capacity": problem.constraints.enforce_storage_capacity,
        },
        "objective": {
            "mission_value_weight": problem.objective.mission_value_weight,
            "penalty_coefficient": problem.objective.penalty_coefficient,
        },
    }


def problem_checksum(problem: SchedulingProblem) -> str:
    """Deterministic checksum over the problem's mathematical content (not id/timestamp)."""
    return sha256_canonical_json(_canonical(problem))


def normalize_problem(problem: SchedulingProblem) -> SchedulingProblem:
    """Validate limits + opportunity-id uniqueness and stamp the canonical checksum."""
    ids = [opp.id for opp in problem.opportunities]
    if len(ids) != len(set(ids)):
        raise ValidationError("opportunity ids must be unique")
    if len(ids) == 0:
        raise ValidationError("a scheduling problem needs at least one opportunity")
    if len(ids) > problem.limits.max_variables:
        raise ValidationError(
            f"problem has {len(ids)} opportunities; exceeds max_variables "
            f"({problem.limits.max_variables})"
        )
    sat_ids = {s.id for s in problem.satellites}
    for opp in problem.opportunities:
        if problem.satellites and opp.satellite_id not in sat_ids:
            raise ValidationError(f"opportunity {opp.id} references unknown satellite")
    for a, b in problem.constraints.mutually_exclusive:
        if a not in ids or b not in ids:
            raise ValidationError("mutually_exclusive references an unknown opportunity")
    for m in problem.constraints.mandatory:
        if m not in ids:
            raise ValidationError("mandatory references an unknown opportunity")
    return problem.model_copy(update={"checksum": problem_checksum(problem)})


def generate_conflicts(problem: SchedulingProblem) -> tuple[SchedulingConflict, ...]:
    """Pairwise conflicts: same-satellite time overlaps + configured mutual exclusions."""
    conflicts: list[SchedulingConflict] = []
    opps = sorted(problem.opportunities, key=lambda o: o.id)
    if problem.constraints.enforce_no_overlap:
        for i in range(len(opps)):
            for j in range(i + 1, len(opps)):
                a, b = opps[i], opps[j]
                if a.satellite_id == b.satellite_id and a.window.overlaps(b.window):
                    conflicts.append(
                        SchedulingConflict(
                            opportunity_a=a.id, opportunity_b=b.id, kind=ConstraintKind.NO_OVERLAP
                        )
                    )
    seen: set[tuple[str, str]] = {(c.opportunity_a, c.opportunity_b) for c in conflicts}
    for ex_a, ex_b in problem.constraints.mutually_exclusive:
        lo, hi = (ex_a, ex_b) if ex_a <= ex_b else (ex_b, ex_a)
        if (lo, hi) not in seen:
            conflicts.append(
                SchedulingConflict(
                    opportunity_a=lo, opportunity_b=hi, kind=ConstraintKind.MUTUAL_EXCLUSION
                )
            )
            seen.add((lo, hi))
    return tuple(conflicts)


def resolved_penalty(problem: SchedulingProblem) -> float:
    """The penalty coefficient used in the QUBO + penalized objective.

    Defaults to (total mission value + 1), which is provably larger than any value gain
    from violating a pairwise/mandatory constraint, so a violation can never be optimal.
    """
    explicit = problem.objective.penalty_coefficient
    if explicit is not None:
        return explicit
    total_value = sum(opp.mission_value for opp in problem.opportunities)
    return total_value + 1.0


def penalty_is_sufficient(problem: SchedulingProblem) -> bool:
    """True if the penalty exceeds the max single-opportunity value (safe lower bound)."""
    penalty = resolved_penalty(problem)
    max_value = max((opp.mission_value for opp in problem.opportunities), default=0.0)
    return penalty > max_value
