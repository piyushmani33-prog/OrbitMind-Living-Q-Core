"""Domain models and translation for bounded observation planning (Phase 4B).

This first slice deliberately stops before persistence, API routes, approval, memory, and
receipt work. It turns a bounded planning request into the existing Phase 4A
``SchedulingProblem`` so the classical optimizer remains the source of scheduling truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import (
    ConstraintSet,
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    SchedulingObjective,
    SchedulingProblem,
    SchedulingProblemLimits,
)
from orbitmind.optimization.problem import normalize_problem

_MAX_HORIZON = timedelta(hours=48)
_FIXTURE_LIMITATION = (
    "fixture-backed observation-planning prototype; access-window geometry is not computed; "
    "not an operational tasking or commanding plan"
)
_DECLARED_LIMITATION = (
    "declared-opportunity observation-planning prototype; access-window geometry is not "
    "computed by OrbitMind; not an operational tasking or commanding plan"
)


class ObservationPlanningSourceMode(StrEnum):
    """Where the candidate opportunities come from for the first Phase 4B slice."""

    FIXTURE = "fixture"
    DECLARED = "declared"


class PlanningVerificationLabel(StrEnum):
    """Honest verification labels for planning outputs before real access geometry exists."""

    VERIFIED_FIXTURE_PLAN = "verified-fixture-plan"
    VERIFIED_DECLARED_OPPORTUNITY_PLAN = "verified-declared-opportunity-plan"


class PlanningHorizon(BaseModel):
    """Bounded UTC interval over which candidate opportunities must fall."""

    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _check(self) -> PlanningHorizon:
        self_start = ensure_utc(self.start)
        self_end = ensure_utc(self.end)
        if self_end <= self_start:
            raise ValueError("planning horizon end must be after start")
        if self_end - self_start > _MAX_HORIZON:
            raise ValueError("planning horizon must be no longer than 48 hours")
        object.__setattr__(self, "start", self_start)
        object.__setattr__(self, "end", self_end)
        return self


class ObservationPlanningRequest(BaseModel):
    """A bounded request that can be translated into a Phase 4A SchedulingProblem.

    ``fixture`` mode is honest about using bundled deterministic opportunities. ``declared``
    mode accepts caller-declared opportunities but still does not compute access geometry.
    """

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=120)
    horizon: PlanningHorizon
    source_mode: ObservationPlanningSourceMode = ObservationPlanningSourceMode.FIXTURE
    fixture_name: str | None = Field(default="default", max_length=80)
    opportunities: tuple[ObservationOpportunity, ...] = ()
    satellites: tuple[SatelliteResource, ...] = ()
    targets: tuple[ObservationTarget, ...] = ()
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    objective: SchedulingObjective = Field(default_factory=SchedulingObjective)
    limits: SchedulingProblemLimits = Field(default_factory=SchedulingProblemLimits)
    requested_by: str = Field(default="local-owner", min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _check_source_shape(self) -> ObservationPlanningRequest:
        if self.source_mode == ObservationPlanningSourceMode.FIXTURE:
            if not self.fixture_name:
                raise ValueError("fixture_name is required for fixture-backed planning")
            if self.opportunities or self.satellites or self.targets:
                raise ValueError(
                    "fixture-backed planning cannot also declare opportunities, satellites, "
                    "or targets"
                )
        else:
            if self.fixture_name is not None:
                raise ValueError("fixture_name must be omitted for declared-opportunity planning")
            if not self.opportunities:
                raise ValueError("declared-opportunity planning requires at least one opportunity")
            if not self.satellites:
                raise ValueError("declared-opportunity planning requires declared satellites")
            if not self.targets:
                raise ValueError("declared-opportunity planning requires declared targets")
        return self


class RequestToProblemTranslation(BaseModel):
    """Result of deterministic request-to-problem translation."""

    model_config = ConfigDict(frozen=True)

    request_checksum: str
    problem: SchedulingProblem
    verification_label: PlanningVerificationLabel
    limitations: tuple[str, ...]


def _dt(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("expected datetime")
    return ensure_utc(value).isoformat()


def _canonical_constraints(constraints: ConstraintSet) -> dict[str, object]:
    return {
        "max_observations": constraints.max_observations,
        "mutually_exclusive": sorted(
            tuple(sorted(pair)) for pair in constraints.mutually_exclusive
        ),
        "mandatory": sorted(constraints.mandatory),
        "per_target_limit": constraints.per_target_limit,
        "min_mission_value": constraints.min_mission_value,
        "enforce_no_overlap": constraints.enforce_no_overlap,
        "enforce_energy_capacity": constraints.enforce_energy_capacity,
        "enforce_storage_capacity": constraints.enforce_storage_capacity,
    }


def _canonical_request(request: ObservationPlanningRequest) -> dict[str, object]:
    """Canonical planning-request payload. Idempotency keys are transport concerns."""

    return {
        "name": request.name,
        "requested_by": request.requested_by,
        "source_mode": request.source_mode.value,
        "fixture_name": request.fixture_name,
        "horizon": {
            "start": _dt(request.horizon.start),
            "end": _dt(request.horizon.end),
        },
        "opportunities": [
            opp.model_dump(mode="json") for opp in sorted(request.opportunities, key=lambda o: o.id)
        ],
        "satellites": [
            sat.model_dump(mode="json") for sat in sorted(request.satellites, key=lambda s: s.id)
        ],
        "targets": [
            target.model_dump(mode="json") for target in sorted(request.targets, key=lambda t: t.id)
        ],
        "constraints": _canonical_constraints(request.constraints),
        "objective": request.objective.model_dump(mode="json"),
        "limits": request.limits.model_dump(mode="json"),
    }


def planning_request_checksum(request: ObservationPlanningRequest) -> str:
    """Deterministic checksum over the user-facing planning request."""

    return sha256_canonical_json(_canonical_request(request))


def _require_within_horizon(
    problem: SchedulingProblem, request: ObservationPlanningRequest
) -> None:
    start = ensure_utc(request.horizon.start)
    end = ensure_utc(request.horizon.end)
    for opp in problem.opportunities:
        opp_start = ensure_utc(opp.window.start)
        opp_end = ensure_utc(opp.window.end)
        if opp_start < start or opp_end > end:
            raise ValidationError(
                f"opportunity {opp.id} falls outside the planning horizon "
                f"({opp_start.isoformat()}..{opp_end.isoformat()})"
            )


def _fixture_problem(request: ObservationPlanningRequest) -> SchedulingProblem:
    try:
        base = fixtures.fixture(str(request.fixture_name))
    except KeyError as exc:
        raise ValidationError(str(exc)) from exc
    return base.model_copy(
        update={
            "name": request.name,
            "constraints": request.constraints,
            "objective": request.objective,
            "limits": request.limits,
            "source": "observation-planning-fixture",
            "provenance": (
                f"Phase 4B fixture-backed observation planning request; fixture="
                f"{request.fixture_name!r}; request_checksum={planning_request_checksum(request)}"
            ),
            "limitations": _FIXTURE_LIMITATION,
        }
    )


def _declared_problem(request: ObservationPlanningRequest) -> SchedulingProblem:
    return SchedulingProblem(
        name=request.name,
        opportunities=list(request.opportunities),
        satellites=list(request.satellites),
        targets=list(request.targets),
        constraints=request.constraints,
        objective=request.objective,
        limits=request.limits,
        source="observation-planning-declared",
        provenance=(
            "Phase 4B declared-opportunity observation planning request; "
            f"request_checksum={planning_request_checksum(request)}"
        ),
        limitations=_DECLARED_LIMITATION,
    )


def translate_request_to_problem(
    request: ObservationPlanningRequest,
) -> RequestToProblemTranslation:
    """Translate a bounded planning request into a normalized SchedulingProblem."""

    if request.source_mode == ObservationPlanningSourceMode.FIXTURE:
        problem = _fixture_problem(request)
        label = PlanningVerificationLabel.VERIFIED_FIXTURE_PLAN
        limitations = (_FIXTURE_LIMITATION,)
    else:
        problem = _declared_problem(request)
        label = PlanningVerificationLabel.VERIFIED_DECLARED_OPPORTUNITY_PLAN
        limitations = (_DECLARED_LIMITATION,)

    normalized = normalize_problem(problem)
    _require_within_horizon(normalized, request)
    return RequestToProblemTranslation(
        request_checksum=planning_request_checksum(request),
        problem=normalized,
        verification_label=label,
        limitations=limitations,
    )
