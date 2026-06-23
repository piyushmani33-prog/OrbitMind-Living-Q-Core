"""Bundled deterministic scheduling fixtures (NOT live CelesTrak/JPL data).

Instances are intentionally tiny so the exact solver enumerates the optimum and the QAOA
circuit stays within a few qubits, keeping CI bounded.
"""

from __future__ import annotations

import datetime as dt

from orbitmind.optimization.models import (
    ConstraintSet,
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    SchedulingObjective,
    SchedulingProblem,
    TimeWindow,
)

_BASE = dt.datetime(2026, 6, 21, 10, 0, 0, tzinfo=dt.UTC)


def _win(start_min: int, end_min: int) -> TimeWindow:
    return TimeWindow(
        start=_BASE + dt.timedelta(minutes=start_min),
        end=_BASE + dt.timedelta(minutes=end_min),
    )


def _opp(
    oid: str,
    sat: str,
    target: str,
    start: int,
    end: int,
    value: float,
    *,
    energy: float = 2.0,
    storage: float = 1.0,
) -> ObservationOpportunity:
    return ObservationOpportunity(
        id=oid,
        satellite_id=sat,
        target_id=target,
        window=_win(start, end),
        mission_value=value,
        duration_seconds=(end - start) * 60.0,
        energy_cost=energy,
        storage_cost=storage,
    )


def default_instance() -> SchedulingProblem:
    """4 opportunities, conflict-only constraints (QUBO fully captures feasibility).

    Optimum: select OPP-2 (6) + OPP-3 (4) = 10 (one per satellite; the two overlaps are
    mutually exclusive within each satellite).
    """
    return SchedulingProblem(
        name="default-4-conflict",
        opportunities=[
            _opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0),
            _opp("OPP-2", "SAT-A", "T2", 15, 45, 6.0),  # overlaps OPP-1 on SAT-A
            _opp("OPP-3", "SAT-B", "T1", 0, 30, 4.0),
            _opp("OPP-4", "SAT-B", "T3", 20, 50, 3.0),  # overlaps OPP-3 on SAT-B
        ],
        satellites=[
            SatelliteResource(id="SAT-A", energy_capacity=100.0, storage_capacity=100.0),
            SatelliteResource(id="SAT-B", energy_capacity=100.0, storage_capacity=100.0),
        ],
        targets=[ObservationTarget(id=t) for t in ("T1", "T2", "T3")],
        constraints=ConstraintSet(),  # conflict-only; capacities non-binding
        objective=SchedulingObjective(),
    )


def resource_bound_instance() -> SchedulingProblem:
    """4 opportunities exercising capacity, max-observations, per-target, and mandatory."""
    return SchedulingProblem(
        name="resource-bound-4",
        opportunities=[
            _opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0, energy=4.0, storage=2.0),
            _opp("OPP-2", "SAT-A", "T2", 35, 65, 4.0, energy=4.0, storage=2.0),
            _opp("OPP-3", "SAT-B", "T1", 0, 30, 3.0, energy=3.0, storage=2.0),
            _opp("OPP-4", "SAT-B", "T3", 40, 70, 6.0, energy=3.0, storage=2.0),
        ],
        satellites=[
            SatelliteResource(id="SAT-A", energy_capacity=10.0, storage_capacity=10.0),
            SatelliteResource(id="SAT-B", energy_capacity=10.0, storage_capacity=10.0),
        ],
        targets=[ObservationTarget(id=t) for t in ("T1", "T2", "T3")],
        constraints=ConstraintSet(max_observations=3, mandatory=("OPP-4",), per_target_limit=1),
        objective=SchedulingObjective(),
    )


def mutual_exclusion_instance() -> SchedulingProblem:
    """3 opportunities, no time overlaps but a configured mutual exclusion (OPP-1, OPP-3)."""
    return SchedulingProblem(
        name="mutual-exclusion-3",
        opportunities=[
            _opp("OPP-1", "SAT-A", "T1", 0, 20, 5.0),
            _opp("OPP-2", "SAT-A", "T2", 25, 45, 4.0),
            _opp("OPP-3", "SAT-B", "T1", 0, 20, 6.0),
        ],
        satellites=[
            SatelliteResource(id="SAT-A", energy_capacity=100.0, storage_capacity=100.0),
            SatelliteResource(id="SAT-B", energy_capacity=100.0, storage_capacity=100.0),
        ],
        targets=[ObservationTarget(id=t) for t in ("T1", "T2")],
        constraints=ConstraintSet(mutually_exclusive=(("OPP-1", "OPP-3"),)),
        objective=SchedulingObjective(),
    )


FIXTURES = {
    "default": default_instance,
    "resource-bound": resource_bound_instance,
    "mutual-exclusion": mutual_exclusion_instance,
}


def fixture(name: str) -> SchedulingProblem:
    if name not in FIXTURES:
        raise KeyError(f"unknown fixture '{name}'; available: {sorted(FIXTURES)}")
    return FIXTURES[name]()
