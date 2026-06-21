"""Deterministic problem normalization, checksum, conflict generation, penalty sizing."""

from __future__ import annotations

import math
from datetime import UTC

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


def _require_finite(value: float, what: str) -> None:
    if not math.isfinite(value):
        raise ValidationError(f"{what} must be finite (got {value})")


def normalize_problem(problem: SchedulingProblem) -> SchedulingProblem:
    """Validate + canonicalize (UTC windows, deduped constraints) and stamp the checksum.

    Rejects malformed problems before checksumming/solving/persistence/Qiskit execution
    (review finding #4): naive datetimes, duplicate/unknown ids, missing satellite/target
    registries, self/duplicate mutual-exclusions, non-finite numerics, and window/duration
    disagreement.
    """
    ids = [opp.id for opp in problem.opportunities]
    if len(ids) == 0:
        raise ValidationError("a scheduling problem needs at least one opportunity")
    if len(ids) != len(set(ids)):
        raise ValidationError("opportunity ids must be unique")
    if len(ids) > problem.limits.max_variables:
        raise ValidationError(
            f"problem has {len(ids)} opportunities; exceeds max_variables "
            f"({problem.limits.max_variables})"
        )
    id_set = set(ids)

    # Registries must be declared, unique, and authoritative (no silent authorization).
    sat_ids = [s.id for s in problem.satellites]
    if len(sat_ids) != len(set(sat_ids)):
        raise ValidationError("satellite ids must be unique")
    target_ids = [t.id for t in problem.targets]
    if len(target_ids) != len(set(target_ids)):
        raise ValidationError("target ids must be unique")
    if not sat_ids:
        raise ValidationError("the satellite registry must declare every referenced satellite")
    if not target_ids:
        raise ValidationError("the target registry must declare every referenced target")
    sat_set, target_set = set(sat_ids), set(target_ids)

    # Objective + capacity finiteness.
    _require_finite(problem.objective.mission_value_weight, "mission_value_weight")
    if not (0.0 < problem.objective.mission_value_weight <= 1_000_000.0):
        raise ValidationError("mission_value_weight must be in (0, 1e6]")
    if problem.objective.penalty_coefficient is not None:
        pc = problem.objective.penalty_coefficient
        if not math.isfinite(pc) or pc <= 0.0:
            raise ValidationError("penalty_coefficient must be positive and finite")
    for sat in problem.satellites:
        _require_finite(sat.energy_capacity, f"satellite {sat.id} energy_capacity")
        _require_finite(sat.storage_capacity, f"satellite {sat.id} storage_capacity")

    canonical_opps = []
    for opp in problem.opportunities:
        if opp.satellite_id not in sat_set:
            raise ValidationError(f"opportunity {opp.id} references undeclared satellite")
        if opp.target_id not in target_set:
            raise ValidationError(f"opportunity {opp.id} references undeclared target")
        for name, val in (
            ("mission_value", opp.mission_value),
            ("duration_seconds", opp.duration_seconds),
            ("energy_cost", opp.energy_cost),
            ("storage_cost", opp.storage_cost),
            ("pointing_cost", opp.pointing_cost),
        ):
            _require_finite(val, f"opportunity {opp.id} {name}")
        window_seconds = (opp.window.end - opp.window.start).total_seconds()
        if not (0.0 < opp.duration_seconds <= window_seconds + 1e-9):
            raise ValidationError(
                f"opportunity {opp.id} duration ({opp.duration_seconds}s) must be > 0 and fit "
                f"within its time window ({window_seconds}s)"
            )
        # Canonicalize the time window to UTC so the checksum is timezone-stable.
        canonical_opps.append(
            opp.model_copy(
                update={
                    "window": opp.window.model_copy(
                        update={
                            "start": opp.window.start.astimezone(UTC),
                            "end": opp.window.end.astimezone(UTC),
                        }
                    )
                }
            )
        )

    # Constraint references + mutual-exclusion canonicalization (distinct, deduped).
    constraints = problem.constraints
    for m in constraints.mandatory:
        if m not in id_set:
            raise ValidationError(f"mandatory references unknown opportunity '{m}'")
    if len(set(constraints.mandatory)) != len(constraints.mandatory):
        raise ValidationError("mandatory opportunities must be unique")
    canonical_mutex: list[tuple[str, str]] = []
    seen_mutex: set[tuple[str, str]] = set()
    for a, b in constraints.mutually_exclusive:
        if a not in id_set or b not in id_set:
            raise ValidationError("mutually_exclusive references an unknown opportunity")
        if a == b:
            raise ValidationError(f"mutual-exclusion endpoints must be distinct (got '{a}' twice)")
        pair = (a, b) if a <= b else (b, a)
        if pair not in seen_mutex:
            seen_mutex.add(pair)
            canonical_mutex.append(pair)
    canonical_constraints = constraints.model_copy(
        update={"mutually_exclusive": tuple(sorted(canonical_mutex))}
    )

    normalized = problem.model_copy(
        update={"opportunities": canonical_opps, "constraints": canonical_constraints}
    )
    return normalized.model_copy(update={"checksum": problem_checksum(normalized)})


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


def total_weighted_value_bound(problem: SchedulingProblem) -> float:
    """An upper bound on the achievable positive weighted mission value: Σ max(0, value)·weight."""
    weight = problem.objective.mission_value_weight
    return sum(max(0.0, opp.mission_value) * weight for opp in problem.opportunities)


def resolved_penalty(problem: SchedulingProblem) -> float:
    """The penalty coefficient used in the QUBO + penalized objective.

    Auto policy (the only one reachable from the public API): a value STRICTLY greater than
    the maximum possible total positive weighted mission value, so selecting any encoded
    violation (conflict pair or unselected mandatory) can never lower the QUBO energy below
    the best feasible assignment. An explicitly-supplied ``penalty_coefficient`` (internal/
    research only) must be positive and finite. See ADR-0026 and penalties.py for the proof.
    """
    explicit = problem.objective.penalty_coefficient
    if explicit is not None:
        if not math.isfinite(explicit) or explicit <= 0.0:
            raise ValidationError("penalty_coefficient must be positive and finite")
        return explicit
    penalty = total_weighted_value_bound(problem) + 1.0
    if not math.isfinite(penalty) or penalty <= 0.0:
        raise ValidationError("computed penalty is not positive/finite (check mission values)")
    return penalty
