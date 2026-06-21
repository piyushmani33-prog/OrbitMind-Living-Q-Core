"""API wire schemas for bounded scheduling optimization (Phase 4A).

Request DTOs are STRICT (``extra='forbid'``) and deliberately do NOT accept server-owned
fields (internal ids, timestamps, provenance, checksums, epistemic/verification status,
limits, software versions, solver status, comparison conclusion, artifact paths, or custom
penalties — review findings #5/#6). Those are stamped by the server. A client may supply a
bounded structural ``id`` per opportunity/target/satellite (a reference within the problem),
which is NOT an internal identity.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.optimization.models import (
    BenchmarkRun,
    ConstraintSet,
    ObservationOpportunity,
    ObservationTarget,
    QuantumExperiment,
    SatelliteResource,
    SchedulingObjective,
    SchedulingProblem,
    SolverResult,
    TimeWindow,
)
from orbitmind.verification.models import VerificationFinding

OPTIMIZATION_DISCLAIMER = (
    "Bounded, simulator-only quantum experiment with MANDATORY classical baselines on the "
    "same normalized instance. 'quantum-competitive' means a defined threshold was met for "
    "this tiny fixture, NEVER general quantum advantage. No experimental quantum result "
    "controls a production mission; every schedule is independently re-verified."
)

_MAX_VARS = 24


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TargetRequest(_Strict):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    priority: int = Field(default=1, ge=0, le=1000)


class SatelliteRequest(_Strict):
    id: str = Field(min_length=1, max_length=64)
    energy_capacity: float = Field(ge=0.0, le=1e12)
    storage_capacity: float = Field(ge=0.0, le=1e12)


class OpportunityRequest(_Strict):
    id: str = Field(min_length=1, max_length=64)
    satellite_id: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=64)
    start: dt.datetime
    end: dt.datetime
    mission_value: float = Field(ge=0.0, le=1_000_000.0)
    duration_seconds: float = Field(gt=0.0, le=1e9)
    energy_cost: float = Field(ge=0.0, le=1e12)
    storage_cost: float = Field(ge=0.0, le=1e12)
    pointing_cost: float = Field(default=0.0, ge=0.0, le=1e12)
    priority: int = Field(default=1, ge=0, le=1000)

    def to_domain(self) -> ObservationOpportunity:
        return ObservationOpportunity(
            id=self.id,
            satellite_id=self.satellite_id,
            target_id=self.target_id,
            window=TimeWindow(start=self.start, end=self.end),
            mission_value=self.mission_value,
            duration_seconds=self.duration_seconds,
            energy_cost=self.energy_cost,
            storage_cost=self.storage_cost,
            pointing_cost=self.pointing_cost,
            priority=self.priority,
            source="api",
            provenance="client-submitted via API (not live CelesTrak/JPL data)",
        )


class ConstraintsRequest(_Strict):
    max_observations: int | None = Field(default=None, ge=0, le=_MAX_VARS)
    mutually_exclusive: list[tuple[str, str]] = Field(default_factory=list, max_length=64)
    mandatory: list[str] = Field(default_factory=list, max_length=_MAX_VARS)
    per_target_limit: int | None = Field(default=None, ge=1, le=_MAX_VARS)
    min_mission_value: float | None = Field(default=None, ge=0.0, le=1e9)
    enforce_no_overlap: bool = True
    enforce_energy_capacity: bool = True
    enforce_storage_capacity: bool = True

    def to_domain(self) -> ConstraintSet:
        return ConstraintSet(
            max_observations=self.max_observations,
            mutually_exclusive=tuple(tuple(p) for p in self.mutually_exclusive),  # type: ignore[misc]
            mandatory=tuple(self.mandatory),
            per_target_limit=self.per_target_limit,
            min_mission_value=self.min_mission_value,
            enforce_no_overlap=self.enforce_no_overlap,
            enforce_energy_capacity=self.enforce_energy_capacity,
            enforce_storage_capacity=self.enforce_storage_capacity,
        )


class ObjectiveRequest(_Strict):
    """Objective weight only. Custom penalty coefficients are NOT accepted (finding #6);
    the server derives a provably-sufficient penalty automatically."""

    mission_value_weight: float = Field(default=1.0, gt=0.0, le=1_000_000.0)


class ProblemCreateRequest(_Strict):
    """A full client-submitted problem spec (no server-owned fields)."""

    name: str = Field(min_length=1, max_length=128)
    opportunities: list[OpportunityRequest] = Field(min_length=1, max_length=_MAX_VARS)
    satellites: list[SatelliteRequest] = Field(min_length=1, max_length=64)
    targets: list[TargetRequest] = Field(min_length=1, max_length=64)
    constraints: ConstraintsRequest = Field(default_factory=ConstraintsRequest)
    objective: ObjectiveRequest = Field(default_factory=ObjectiveRequest)

    def to_domain(self) -> SchedulingProblem:
        return SchedulingProblem(
            name=self.name,
            opportunities=[o.to_domain() for o in self.opportunities],
            satellites=[
                SatelliteResource(
                    id=s.id, energy_capacity=s.energy_capacity, storage_capacity=s.storage_capacity
                )
                for s in self.satellites
            ],
            targets=[
                ObservationTarget(id=t.id, name=t.name, priority=t.priority) for t in self.targets
            ],
            constraints=self.constraints.to_domain(),
            objective=SchedulingObjective(mission_value_weight=self.objective.mission_value_weight),
            source="api",
            provenance="client-submitted via API",
        )


class CreateProblemRequest(_Strict):
    """Create a problem from a bundled fixture OR a strict structured spec (exactly one)."""

    fixture: str | None = None
    problem: ProblemCreateRequest | None = None

    @model_validator(mode="after")
    def _check(self) -> CreateProblemRequest:
        if (self.fixture is None) == (self.problem is None):
            raise ValueError("provide exactly one of 'fixture' or 'problem'")
        return self


class ClassicalSolveRequest(_Strict):
    solver: Literal["exact", "greedy"]
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=60.0)


class QuantumSolveRequest(_Strict):
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    shots: int = Field(default=2048, ge=1, le=16384)
    optimizer_iterations: int = Field(default=24, ge=1, le=128)
    qaoa_layers: int = Field(default=1, ge=1, le=3)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=60.0)


class BenchmarkRequest(_Strict):
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    shots: int = Field(default=2048, ge=1, le=16384)
    optimizer_iterations: int = Field(default=24, ge=1, le=128)
    qaoa_layers: int = Field(default=1, ge=1, le=3)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=60.0)
    run_quantum: bool = True
    generate_artifacts: bool = False
    competitive_relative_gap: float = Field(default=0.0, ge=0.0, le=1.0)
    min_feasible_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)


class ProblemListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SchedulingProblem]


class SolverResultResponse(BaseModel):
    result: SolverResult
    disclaimer: str = OPTIMIZATION_DISCLAIMER


class QuantumExperimentResponse(BaseModel):
    experiment: QuantumExperiment
    disclaimer: str = OPTIMIZATION_DISCLAIMER


class BenchmarkResponse(BaseModel):
    run: BenchmarkRun
    findings: list[VerificationFinding]
    verified: bool
    disclaimer: str = OPTIMIZATION_DISCLAIMER


class RunListResponse(BaseModel):
    items: list[dict[str, object]]


class ArtifactListResponse(BaseModel):
    scope_id: str
    artifacts: list[dict[str, str]]
    disclaimer: str = OPTIMIZATION_DISCLAIMER


__all__ = [
    "OPTIMIZATION_DISCLAIMER",
    "ArtifactListResponse",
    "BenchmarkRequest",
    "BenchmarkResponse",
    "ClassicalSolveRequest",
    "CreateProblemRequest",
    "ProblemListResponse",
    "QuantumExperimentResponse",
    "QuantumSolveRequest",
    "RunListResponse",
    "SolverResultResponse",
]
