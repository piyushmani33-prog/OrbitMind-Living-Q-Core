"""The shared deterministic schedule evaluator (the independent verifier).

Every solver result — classical or quantum — is re-evaluated here; a solver's own
feasibility/objective claim is never trusted. The penalized objective is defined so that
``-penalized_objective(x)`` equals the QUBO energy (see qubo.py), which is exhaustively
verified on tiny instances.
"""

from __future__ import annotations

from collections import Counter

from orbitmind.optimization.models import (
    ConstraintKind,
    ConstraintViolation,
    ScheduleEvaluation,
    SchedulingProblem,
)
from orbitmind.optimization.problem import (
    generate_conflicts,
    resolved_penalty,
    variable_order,
)


class Evaluator:
    """Precomputes problem structure once, then evaluates any candidate selection."""

    def __init__(self, problem: SchedulingProblem) -> None:
        self.problem = problem
        self.order = variable_order(problem)
        self.index = {opp_id: i for i, opp_id in enumerate(self.order)}
        self.penalty = resolved_penalty(problem)
        self.weight = problem.objective.mission_value_weight
        self._opp = {opp.id: opp for opp in problem.opportunities}
        self._conflicts = generate_conflicts(problem)
        self._mandatory = set(problem.constraints.mandatory)

    # -- entry points -------------------------------------------------------
    def evaluate(self, selected: frozenset[str] | set[str]) -> ScheduleEvaluation:
        selected = frozenset(selected) & set(self.order)
        raw_value = sum(self._opp[i].mission_value for i in selected)
        weighted_value = raw_value * self.weight
        total_energy = sum(self._opp[i].energy_cost for i in selected)
        total_storage = sum(self._opp[i].storage_cost for i in selected)

        violations: list[ConstraintViolation] = []
        penalized_count = 0  # conflict pairs both-selected + mandatory not selected

        # Pairwise conflicts (no-overlap + mutual-exclusion) — penalized + hard.
        for conflict in self._conflicts:
            if conflict.opportunity_a in selected and conflict.opportunity_b in selected:
                penalized_count += 1
                violations.append(
                    ConstraintViolation(
                        kind=conflict.kind,
                        detail=f"{conflict.opportunity_a} & {conflict.opportunity_b} both selected",
                        magnitude=1.0,
                    )
                )
        # Mandatory — penalized + hard.
        for mandatory in sorted(self._mandatory):
            if mandatory not in selected:
                penalized_count += 1
                violations.append(
                    ConstraintViolation(
                        kind=ConstraintKind.MANDATORY,
                        detail=f"mandatory opportunity {mandatory} not selected",
                        magnitude=1.0,
                    )
                )

        constraints = self.problem.constraints
        # Max observations (hard only).
        if (
            constraints.max_observations is not None
            and len(selected) > constraints.max_observations
        ):
            violations.append(
                ConstraintViolation(
                    kind=ConstraintKind.MAX_OBSERVATIONS,
                    detail=f"{len(selected)} selected > max {constraints.max_observations}",
                    magnitude=float(len(selected) - constraints.max_observations),
                )
            )
        # Energy / storage capacity, per satellite (hard only).
        if constraints.enforce_energy_capacity:
            violations.extend(self._capacity_violations(selected, "energy"))
        if constraints.enforce_storage_capacity:
            violations.extend(self._capacity_violations(selected, "storage"))
        # Per-target limit (hard only).
        if constraints.per_target_limit is not None:
            per_target = Counter(self._opp[i].target_id for i in selected)
            for target_id, count in sorted(per_target.items()):
                if count > constraints.per_target_limit:
                    violations.append(
                        ConstraintViolation(
                            kind=ConstraintKind.PER_TARGET_LIMIT,
                            detail=f"target {target_id}: {count} > {constraints.per_target_limit}",
                            magnitude=float(count - constraints.per_target_limit),
                        )
                    )
        # Minimum mission value (hard only; compared against the weighted objective).
        if (
            constraints.min_mission_value is not None
            and weighted_value < constraints.min_mission_value
        ):
            violations.append(
                ConstraintViolation(
                    kind=ConstraintKind.MIN_MISSION_VALUE,
                    detail=f"value {weighted_value} < min {constraints.min_mission_value}",
                    magnitude=constraints.min_mission_value - weighted_value,
                )
            )

        constraint_penalty = self.penalty * penalized_count
        penalized_objective = weighted_value - constraint_penalty
        feasible = len(violations) == 0
        return ScheduleEvaluation(
            problem_checksum=self.problem.checksum,
            selected_opportunity_ids=tuple(sorted(selected)),
            feasible=feasible,
            raw_mission_value=raw_value,
            weighted_mission_value=weighted_value,
            constraint_penalty=constraint_penalty,
            penalized_objective=penalized_objective,
            objective_value=weighted_value,
            total_energy=total_energy,
            total_storage=total_storage,
            violations=tuple(violations),
        )

    def evaluate_bitstring(self, bits: str) -> ScheduleEvaluation:
        """Decode a string in variable_order (index 0 = first char). Validates binary width."""
        if len(bits) != len(self.order):
            raise ValueError(f"bitstring length {len(bits)} != num vars {len(self.order)}")
        if any(c not in "01" for c in bits):
            raise ValueError("bitstring must contain only '0' and '1'")
        selected = {self.order[i] for i, b in enumerate(bits) if b == "1"}
        return self.evaluate(selected)

    def _capacity_violations(
        self, selected: frozenset[str] | set[str], kind: str
    ) -> list[ConstraintViolation]:
        cap_attr = "energy_capacity" if kind == "energy" else "storage_capacity"
        cost_attr = "energy_cost" if kind == "energy" else "storage_cost"
        vkind = (
            ConstraintKind.ENERGY_CAPACITY if kind == "energy" else ConstraintKind.STORAGE_CAPACITY
        )
        out: list[ConstraintViolation] = []
        per_sat: dict[str, float] = {}
        for opp_id in selected:
            opp = self._opp[opp_id]
            per_sat[opp.satellite_id] = per_sat.get(opp.satellite_id, 0.0) + getattr(opp, cost_attr)
        caps = {s.id: getattr(s, cap_attr) for s in self.problem.satellites}
        for sat_id, used in sorted(per_sat.items()):
            cap = caps.get(sat_id)
            if cap is not None and used > cap + 1e-9:
                out.append(
                    ConstraintViolation(
                        kind=vkind,
                        detail=f"satellite {sat_id}: {kind} {used} > capacity {cap}",
                        magnitude=used - cap,
                    )
                )
        return out
