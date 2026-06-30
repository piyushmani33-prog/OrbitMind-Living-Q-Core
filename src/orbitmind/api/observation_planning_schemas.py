"""API wire schemas for bounded observation planning.

This HTTP surface is deliberately non-operational: it plans over fixture-backed or
caller-declared opportunities only. It does not compute access-window geometry,
approve command plans, call live providers, or invoke quantum execution.
"""

from __future__ import annotations

import datetime as dt
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from orbitmind.observation_planning import (
    AuthoritativePlanningSolver,
    ObservationPlanDetails,
    ObservationPlanningExecutionDetails,
    ObservationPlanningRequest,
    ObservationPlanningRequestDetails,
    ObservationPlanningRequestSummary,
    ObservationPlanningRunDetails,
    ObservationPlanningRunSummary,
    ObservationPlanningSourceMode,
    ObservationPlanSummary,
    PersistedObservationPlanningExecution,
    PlanningHorizon,
    PlanningOptimalityLabel,
    PlanningResultStatus,
    PlanningVerificationLabel,
    ProvenanceAnchoredPlanningExecution,
)
from orbitmind.observation_planning.provenance import (
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.optimization.models import (
    ConstraintSet,
    ExperimentStatus,
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    ScheduleEvaluation,
    SchedulingObjective,
    SchedulingProblemLimits,
    TimeWindow,
)
from orbitmind.persistence.observation_planning_link_repository import StoredProvenancePlanningLink

OBSERVATION_PLANNING_DISCLAIMER = (
    "Bounded observation planning over fixture-backed or user-declared opportunities. "
    "Results are verified only against declared inputs and scheduling constraints; OrbitMind "
    "does not compute access-window geometry here, does not approve commanding, and does not "
    "treat quantum execution as authoritative."
)

PROVENANCE_ANCHORED_EXECUTION_DISCLAIMER = (
    "Provenance-anchored bounded observation planning over authenticated fixture-backed, "
    "user-declared, or geometry-derived eligibility windows. Geometry-derived eligibility "
    "comes from pinned/offline deterministic model output; eligibility windows do not prove "
    "live tracking, orbital visibility, operational access, taskability, approval, command "
    "readiness, or signed receipt status. Planning remains classically authoritative; "
    "quantum execution is not authoritative."
)

_MAX_OPPORTUNITIES = 24
_MAX_ASSETS = 24
_MAX_TARGETS = 24
_MAX_MANDATORY_IDS = 24
_MAX_MUTUAL_EXCLUSION_GROUPS = 276
_MAX_SELECTED_WINDOWS = 24
_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlanningHorizonRequest(_Strict):
    start: dt.datetime
    end: dt.datetime

    @field_validator("start", "end")
    @classmethod
    def _aware_utc(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamps must be timezone-aware")
        return value.astimezone(dt.UTC)

    def to_domain(self) -> PlanningHorizon:
        return PlanningHorizon(start=self.start, end=self.end)


class TargetRequest(_Strict):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="", max_length=128)
    priority: int = Field(default=1, ge=0, le=1000)

    def to_domain(self) -> ObservationTarget:
        return ObservationTarget(id=self.id, name=self.name, priority=self.priority)


class SatelliteRequest(_Strict):
    id: str = Field(min_length=1, max_length=64)
    energy_capacity: float = Field(ge=0.0, le=1e12, allow_inf_nan=False)
    storage_capacity: float = Field(ge=0.0, le=1e12, allow_inf_nan=False)

    def to_domain(self) -> SatelliteResource:
        return SatelliteResource(
            id=self.id,
            energy_capacity=self.energy_capacity,
            storage_capacity=self.storage_capacity,
        )


class OpportunityRequest(_Strict):
    id: str = Field(min_length=1, max_length=64)
    satellite_id: str = Field(min_length=1, max_length=64)
    target_id: str = Field(min_length=1, max_length=64)
    start: dt.datetime
    end: dt.datetime
    mission_value: float = Field(ge=0.0, le=1_000_000.0, allow_inf_nan=False)
    energy_cost: float = Field(ge=0.0, le=1e12, allow_inf_nan=False)
    storage_cost: float = Field(ge=0.0, le=1e12, allow_inf_nan=False)
    pointing_cost: float = Field(default=0.0, ge=0.0, le=1e12, allow_inf_nan=False)
    priority: int = Field(default=1, ge=0, le=1000)

    @field_validator("start", "end")
    @classmethod
    def _aware_utc(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("opportunity timestamps must be timezone-aware")
        return value.astimezone(dt.UTC)

    @model_validator(mode="after")
    def _check_window(self) -> Self:
        if self.end <= self.start:
            raise ValueError("opportunity end must be after start")
        return self

    def to_domain(self) -> ObservationOpportunity:
        return ObservationOpportunity(
            id=self.id,
            satellite_id=self.satellite_id,
            target_id=self.target_id,
            window=TimeWindow(start=self.start, end=self.end),
            mission_value=self.mission_value,
            duration_seconds=(self.end - self.start).total_seconds(),
            energy_cost=self.energy_cost,
            storage_cost=self.storage_cost,
            pointing_cost=self.pointing_cost,
            priority=self.priority,
            source="api-declared",
            provenance=(
                "client-declared opportunity via bounded observation-planning API; "
                "access-window geometry was not computed by OrbitMind"
            ),
            limitations=(
                "declared opportunity; non-operational and not proof of real satellite taskability"
            ),
        )


class ConstraintsRequest(_Strict):
    max_observations: int | None = Field(default=None, ge=0, le=_MAX_OPPORTUNITIES)
    mutually_exclusive: tuple[tuple[str, str], ...] = Field(
        default=(), max_length=_MAX_MUTUAL_EXCLUSION_GROUPS
    )
    mandatory: tuple[str, ...] = Field(default=(), max_length=_MAX_MANDATORY_IDS)
    per_target_limit: int | None = Field(default=None, ge=1, le=_MAX_OPPORTUNITIES)
    min_mission_value: float | None = Field(default=None, ge=0.0, le=1e9, allow_inf_nan=False)
    enforce_no_overlap: bool = True
    enforce_energy_capacity: bool = True
    enforce_storage_capacity: bool = True

    def to_domain(self) -> ConstraintSet:
        return ConstraintSet(
            max_observations=self.max_observations,
            mutually_exclusive=self.mutually_exclusive,
            mandatory=self.mandatory,
            per_target_limit=self.per_target_limit,
            min_mission_value=self.min_mission_value,
            enforce_no_overlap=self.enforce_no_overlap,
            enforce_energy_capacity=self.enforce_energy_capacity,
            enforce_storage_capacity=self.enforce_storage_capacity,
        )


class ObjectiveRequest(_Strict):
    mission_value_weight: float = Field(default=1.0, gt=0.0, le=1_000_000.0, allow_inf_nan=False)

    def to_domain(self) -> SchedulingObjective:
        return SchedulingObjective(mission_value_weight=self.mission_value_weight)


class PlanningLimitsRequest(_Strict):
    max_variables: int = Field(default=20, ge=1, le=24)
    exact_max_variables: int = Field(default=20, ge=1, le=22)
    max_timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0, allow_inf_nan=False)

    def to_domain(self) -> SchedulingProblemLimits:
        return SchedulingProblemLimits(
            max_variables=self.max_variables,
            exact_max_variables=self.exact_max_variables,
            max_timeout_seconds=self.max_timeout_seconds,
        )


class ObservationPlanningExecuteRequest(_Strict):
    name: str = Field(min_length=1, max_length=120)
    horizon: PlanningHorizonRequest
    source_mode: ObservationPlanningSourceMode = ObservationPlanningSourceMode.FIXTURE
    fixture_name: str | None = Field(default="default", max_length=80)
    opportunities: tuple[OpportunityRequest, ...] = Field(default=(), max_length=_MAX_OPPORTUNITIES)
    satellites: tuple[SatelliteRequest, ...] = Field(default=(), max_length=_MAX_ASSETS)
    targets: tuple[TargetRequest, ...] = Field(default=(), max_length=_MAX_TARGETS)
    constraints: ConstraintsRequest = Field(default_factory=ConstraintsRequest)
    objective: ObjectiveRequest = Field(default_factory=ObjectiveRequest)
    limits: PlanningLimitsRequest = Field(default_factory=PlanningLimitsRequest)
    requested_by: str = Field(default="local-owner", min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    def to_domain(self) -> ObservationPlanningRequest:
        return ObservationPlanningRequest(
            name=self.name,
            horizon=self.horizon.to_domain(),
            source_mode=self.source_mode,
            fixture_name=self.fixture_name,
            opportunities=tuple(item.to_domain() for item in self.opportunities),
            satellites=tuple(item.to_domain() for item in self.satellites),
            targets=tuple(item.to_domain() for item in self.targets),
            constraints=self.constraints.to_domain(),
            objective=self.objective.to_domain(),
            limits=self.limits.to_domain(),
            requested_by=self.requested_by,
            idempotency_key=self.idempotency_key,
        )


class ProvenanceAnchoredExecutionRequest(_Strict):
    eligibility_set_id: str | None = Field(default=None, min_length=1, max_length=36)
    eligibility_set_checksum: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
        pattern=_SHA256_PATTERN,
    )
    requested_by: str = Field(min_length=1, max_length=120)
    selected_window_ids: tuple[str, ...] | None = Field(
        default=None,
        max_length=_MAX_SELECTED_WINDOWS,
    )
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("eligibility_set_id", "eligibility_set_checksum", "requested_by")
    @classmethod
    def _clean_required_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.strip() != value:
            raise ValueError("value must be unpadded")
        return value

    @field_validator("idempotency_key")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value.strip() != value:
            raise ValueError("idempotency_key must be unpadded")
        return value

    @field_validator("selected_window_ids")
    @classmethod
    def _clean_selected_window_ids(
        cls,
        value: tuple[str, ...] | None,
    ) -> tuple[str, ...] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("selected_window_ids cannot be empty when supplied")
        for window_id in value:
            if not window_id or window_id.strip() != window_id or len(window_id) > 80:
                raise ValueError("selected_window_ids must be non-empty, bounded, and unpadded")
        if len(set(value)) != len(value):
            raise ValueError("selected_window_ids must be unique")
        return value

    @model_validator(mode="after")
    def _exactly_one_lookup(self) -> Self:
        if (self.eligibility_set_id is None) == (self.eligibility_set_checksum is None):
            raise ValueError("provide exactly one eligibility_set_id or eligibility_set_checksum")
        return self


class PlanningHorizonView(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: dt.datetime
    end: dt.datetime


class ObservationPlanningRequestView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    horizon: PlanningHorizonView
    source_mode: ObservationPlanningSourceMode
    fixture_name: str | None
    opportunities: tuple[ObservationOpportunity, ...]
    satellites: tuple[SatelliteResource, ...]
    targets: tuple[ObservationTarget, ...]
    constraints: ConstraintSet
    objective: SchedulingObjective
    limits: SchedulingProblemLimits
    requested_by: str

    @classmethod
    def from_domain(cls, request: ObservationPlanningRequest) -> ObservationPlanningRequestView:
        return cls(
            name=request.name,
            horizon=PlanningHorizonView(start=request.horizon.start, end=request.horizon.end),
            source_mode=request.source_mode,
            fixture_name=request.fixture_name,
            opportunities=request.opportunities,
            satellites=request.satellites,
            targets=request.targets,
            constraints=request.constraints,
            objective=request.objective,
            limits=request.limits,
            requested_by=request.requested_by,
        )


class ObservationPlanningExecutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: str
    run_id: str
    plan_id: str | None
    owner_id: str
    request_created: bool
    run_created: bool
    plan_created: bool
    request_checksum: str
    problem_checksum: str
    scientific_identity_checksum: str
    source_mode: ObservationPlanningSourceMode
    final_status: PlanningResultStatus
    selected_solver: AuthoritativePlanningSolver | None
    solver_execution_status: ExperimentStatus | None
    optimality_label: PlanningOptimalityLabel
    verification_label: PlanningVerificationLabel | None
    feasible: bool
    objective_value: float | None
    limitations: tuple[str, ...]
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER

    @classmethod
    def from_execution(
        cls, execution: PersistedObservationPlanningExecution
    ) -> ObservationPlanningExecutionResponse:
        result = execution.result
        return cls(
            request_id=execution.request_id,
            run_id=execution.run_id,
            plan_id=execution.plan_id,
            owner_id=execution.owner_id,
            request_created=execution.request_created,
            run_created=execution.run_created,
            plan_created=execution.plan_created,
            request_checksum=execution.request_checksum,
            problem_checksum=execution.problem_checksum,
            scientific_identity_checksum=execution.scientific_identity_checksum,
            source_mode=result.source_mode,
            final_status=execution.final_status,
            selected_solver=result.selected_solver,
            solver_execution_status=result.solver_execution_status,
            optimality_label=result.optimality_label,
            verification_label=result.verification_label,
            feasible=execution.feasible,
            objective_value=result.objective_value,
            limitations=result.limitations,
        )


class ProvenanceAnchoredExecutionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner_id: str
    provenance_checksum: str
    eligibility_set_checksum: str
    preparation_checksum: str
    planning_request_checksum: str
    planning_request_id: str
    planning_run_id: str
    observation_plan_id: str | None
    link_id: str
    link_checksum: str
    selected_window_ids: tuple[str, ...]
    planning_status: PlanningResultStatus
    authoritative_solver: AuthoritativePlanningSolver | None
    optimality: PlanningOptimalityLabel
    feasible: bool
    independent_objective: float | None
    request_created: bool
    run_created: bool
    source_type: PinnedInputSourceType
    verification_status: ScientificInputVerificationStatus
    limitations: tuple[str, ...]
    disclaimer: str = PROVENANCE_ANCHORED_EXECUTION_DISCLAIMER

    @classmethod
    def from_execution(
        cls,
        execution: ProvenanceAnchoredPlanningExecution,
    ) -> ProvenanceAnchoredExecutionResponse:
        return cls(
            owner_id=execution.owner_id,
            provenance_checksum=execution.provenance_checksum,
            eligibility_set_checksum=execution.eligibility_set_checksum,
            preparation_checksum=execution.preparation_checksum,
            planning_request_checksum=execution.planning_request_checksum,
            planning_request_id=execution.planning_request_id,
            planning_run_id=execution.planning_run_id,
            observation_plan_id=execution.observation_plan_id,
            link_id=execution.link_record_id,
            link_checksum=execution.link_checksum,
            selected_window_ids=execution.selected_window_ids,
            planning_status=execution.planning_status,
            authoritative_solver=execution.authoritative_solver,
            optimality=execution.optimality,
            feasible=execution.feasible,
            independent_objective=execution.independent_objective,
            request_created=execution.request_created,
            run_created=execution.run_created,
            source_type=execution.source_type,
            verification_status=execution.source_verification_status,
            limitations=execution.limitations,
        )


class ObservationPlanningRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    name: str
    request_checksum: str
    source_mode: ObservationPlanningSourceMode
    created_at: dt.datetime
    request: ObservationPlanningRequestView
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER

    @classmethod
    def from_details(
        cls, details: ObservationPlanningRequestDetails
    ) -> ObservationPlanningRequestResponse:
        summary = details.summary
        return cls(
            id=summary.id,
            owner_id=summary.owner_id,
            name=summary.name,
            request_checksum=summary.request_checksum,
            source_mode=summary.source_mode,
            created_at=summary.created_at,
            request=ObservationPlanningRequestView.from_domain(details.request),
        )


class ObservationPlanningRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    problem_checksum: str
    scientific_identity_checksum: str
    source_mode: ObservationPlanningSourceMode
    status: PlanningResultStatus
    selected_solver: AuthoritativePlanningSolver | None
    solver_execution_status: ExperimentStatus | None
    optimality_label: PlanningOptimalityLabel
    verification_label: PlanningVerificationLabel | None
    feasible: bool
    objective_value: float | None
    created_at: dt.datetime
    completed_at: dt.datetime | None
    plan_id: str | None
    limitations: tuple[str, ...]
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER

    @classmethod
    def from_details(cls, details: ObservationPlanningRunDetails) -> ObservationPlanningRunResponse:
        return cls.from_summary(
            details.summary,
            scientific_identity_checksum=details.scientific_identity_checksum,
        )

    @classmethod
    def from_summary(
        cls,
        summary: ObservationPlanningRunSummary,
        *,
        scientific_identity_checksum: str,
    ) -> ObservationPlanningRunResponse:
        return cls(
            id=summary.id,
            request_id=summary.request_id,
            owner_id=summary.owner_id,
            request_checksum=summary.request_checksum,
            problem_checksum=summary.problem_checksum,
            scientific_identity_checksum=scientific_identity_checksum,
            source_mode=summary.source_mode,
            status=summary.status,
            selected_solver=summary.selected_solver,
            solver_execution_status=summary.solver_execution_status,
            optimality_label=summary.optimality_label,
            verification_label=summary.verification_label,
            feasible=summary.feasible,
            objective_value=summary.objective_value,
            created_at=summary.created_at,
            completed_at=summary.completed_at,
            plan_id=summary.plan_id,
            limitations=summary.limitations,
        )


class ObservationPlanResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str
    owner_id: str
    problem_checksum: str
    selected_opportunity_count: int
    selected_opportunity_ids: tuple[str, ...]
    scientific_identity_checksum: str
    created_at: dt.datetime
    limitations: tuple[str, ...]
    evaluation: ScheduleEvaluation
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER

    @classmethod
    def from_details(cls, details: ObservationPlanDetails) -> ObservationPlanResponse:
        summary = details.summary
        return cls(
            id=summary.id,
            run_id=summary.run_id,
            owner_id=summary.owner_id,
            problem_checksum=summary.problem_checksum,
            selected_opportunity_count=summary.selected_opportunity_count,
            selected_opportunity_ids=details.selected_opportunity_ids,
            scientific_identity_checksum=summary.scientific_identity_checksum,
            created_at=summary.created_at,
            limitations=summary.limitations,
            evaluation=details.evaluation,
        )


class ProvenancePlanningLinkResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    provenance_record_id: str
    provenance_checksum: str
    eligibility_set_record_id: str
    eligibility_set_checksum: str
    preparation_checksum: str
    planning_request_checksum: str
    planning_scientific_identity_checksum: str
    planning_request_id: str
    planning_run_id: str
    observation_plan_id: str | None
    selected_window_ids: tuple[str, ...]
    planning_status: PlanningResultStatus
    authoritative_solver: AuthoritativePlanningSolver | None
    optimality: PlanningOptimalityLabel
    feasible: bool
    independent_objective: float | None
    limitations: tuple[str, ...]
    link_checksum: str
    disclaimer: str = PROVENANCE_ANCHORED_EXECUTION_DISCLAIMER

    @classmethod
    def from_link(cls, link: StoredProvenancePlanningLink) -> ProvenancePlanningLinkResponse:
        return cls(
            id=link.id,
            owner_id=link.owner_id,
            provenance_record_id=link.provenance_record_id,
            provenance_checksum=link.provenance_checksum,
            eligibility_set_record_id=link.eligibility_set_record_id,
            eligibility_set_checksum=link.eligibility_set_checksum,
            preparation_checksum=link.preparation_checksum,
            planning_request_checksum=link.planning_request_checksum,
            planning_scientific_identity_checksum=link.planning_scientific_identity_checksum,
            planning_request_id=link.planning_request_id,
            planning_run_id=link.planning_run_id,
            observation_plan_id=link.observation_plan_id,
            selected_window_ids=link.selected_window_ids,
            planning_status=PlanningResultStatus(link.planning_status),
            authoritative_solver=AuthoritativePlanningSolver(link.authoritative_solver)
            if link.authoritative_solver is not None
            else None,
            optimality=PlanningOptimalityLabel(link.optimality_label),
            feasible=link.feasible,
            independent_objective=link.objective_value,
            limitations=link.limitations,
            link_checksum=link.link_checksum,
        )


class ObservationPlanningExecutionDetailsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    request: ObservationPlanningRequestResponse
    run: ObservationPlanningRunResponse
    plan: ObservationPlanResponse | None
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER

    @classmethod
    def from_details(
        cls, details: ObservationPlanningExecutionDetails
    ) -> ObservationPlanningExecutionDetailsResponse:
        return cls(
            request=ObservationPlanningRequestResponse.from_details(details.request),
            run=ObservationPlanningRunResponse.from_details(details.run),
            plan=ObservationPlanResponse.from_details(details.plan)
            if details.plan is not None
            else None,
        )


class ObservationPlanningRequestSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    name: str
    request_checksum: str
    source_mode: ObservationPlanningSourceMode
    created_at: dt.datetime

    @classmethod
    def from_summary(
        cls, summary: ObservationPlanningRequestSummary
    ) -> ObservationPlanningRequestSummaryResponse:
        return cls(**summary.model_dump())


class ObservationPlanningRunSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    problem_checksum: str
    source_mode: ObservationPlanningSourceMode
    status: PlanningResultStatus
    selected_solver: AuthoritativePlanningSolver | None
    solver_execution_status: ExperimentStatus | None
    optimality_label: PlanningOptimalityLabel
    verification_label: PlanningVerificationLabel | None
    feasible: bool
    objective_value: float | None
    created_at: dt.datetime
    completed_at: dt.datetime | None
    plan_id: str | None
    limitations: tuple[str, ...]

    @classmethod
    def from_summary(
        cls, summary: ObservationPlanningRunSummary
    ) -> ObservationPlanningRunSummaryResponse:
        return cls(**summary.model_dump())


class ObservationPlanSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str
    owner_id: str
    problem_checksum: str
    selected_opportunity_count: int
    scientific_identity_checksum: str
    created_at: dt.datetime
    limitations: tuple[str, ...]

    @classmethod
    def from_summary(cls, summary: ObservationPlanSummary) -> ObservationPlanSummaryResponse:
        return cls(**summary.model_dump())


class ObservationPlanningRequestListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationPlanningRequestSummaryResponse, ...]
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER


class ObservationPlanningRunListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationPlanningRunSummaryResponse, ...]
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER


class ObservationPlanListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationPlanSummaryResponse, ...]
    disclaimer: str = OBSERVATION_PLANNING_DISCLAIMER
