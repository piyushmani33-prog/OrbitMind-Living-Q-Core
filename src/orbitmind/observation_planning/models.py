"""Domain models and translation for bounded observation planning (Phase 4B).

This first slice deliberately stops before persistence, API routes, approval, memory, and
receipt work. It turns a bounded planning request into the existing Phase 4A
``SchedulingProblem`` so the classical optimizer remains the source of scheduling truth.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import (
    CandidateSchedule,
    ConstraintSet,
    ExperimentStatus,
    ObservationOpportunity,
    ObservationTarget,
    OptimalityStatus,
    SatelliteResource,
    ScheduleEvaluation,
    SchedulingObjective,
    SchedulingProblem,
    SchedulingProblemLimits,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.problem import normalize_problem

_MAX_OPPORTUNITIES = 24
_MAX_ASSETS = 24
_MAX_TARGETS = 24
_MAX_MANDATORY_IDS = 24
_MAX_MUTUAL_EXCLUSION_GROUPS = 276  # 24 * 23 / 2 complete pairwise conflict graph.
_MAX_MUTUAL_EXCLUSION_MEMBERS = 2
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


class AuthoritativePlanningSolver(StrEnum):
    """Classical solver selected as the authoritative Phase 4B.1 planning source."""

    EXACT = "exact"
    GREEDY = "greedy"


class PlanningResultStatus(StrEnum):
    """Typed in-memory planning outcomes for the non-persistent Phase 4B.1 boundary."""

    VERIFIED_FEASIBLE = "verified-feasible"
    INFEASIBLE = "infeasible"
    TIMED_OUT = "timed-out"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"
    FAILED = "failed"


class PlanningOptimalityLabel(StrEnum):
    """Honest optimality labels for classically generated observation plans."""

    OPTIMAL = "optimal"
    HEURISTIC = "heuristic"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


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
    opportunities: tuple[ObservationOpportunity, ...] = Field(
        default=(), max_length=_MAX_OPPORTUNITIES
    )
    satellites: tuple[SatelliteResource, ...] = Field(default=(), max_length=_MAX_ASSETS)
    targets: tuple[ObservationTarget, ...] = Field(default=(), max_length=_MAX_TARGETS)
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    objective: SchedulingObjective = Field(default_factory=SchedulingObjective)
    limits: SchedulingProblemLimits = Field(default_factory=SchedulingProblemLimits)
    requested_by: str = Field(default="local-owner", min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _check_source_shape(self) -> ObservationPlanningRequest:
        self._check_request_bounds()
        self._check_ids()
        self._check_finite_values()
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

    def _check_request_bounds(self) -> None:
        max_opportunities = min(self.limits.max_variables, _MAX_OPPORTUNITIES)
        if len(self.opportunities) > max_opportunities:
            raise ValueError(f"opportunities must contain at most {max_opportunities} entries")
        if len(self.satellites) > _MAX_ASSETS:
            raise ValueError(f"satellites/assets must contain at most {_MAX_ASSETS} entries")
        if len(self.targets) > _MAX_TARGETS:
            raise ValueError(f"targets must contain at most {_MAX_TARGETS} entries")
        max_mandatory = min(max_opportunities, _MAX_MANDATORY_IDS)
        if len(self.constraints.mandatory) > max_mandatory:
            raise ValueError(f"mandatory IDs must contain at most {max_mandatory} entries")
        if len(self.constraints.mutually_exclusive) > _MAX_MUTUAL_EXCLUSION_GROUPS:
            raise ValueError(
                "mutual-exclusion constraints must contain at most "
                f"{_MAX_MUTUAL_EXCLUSION_GROUPS} groups"
            )
        for group in self.constraints.mutually_exclusive:
            if len(group) != _MAX_MUTUAL_EXCLUSION_MEMBERS:
                raise ValueError("each mutual-exclusion group must contain exactly two IDs")

    def _check_ids(self) -> None:
        _require_unique_ids((opp.id for opp in self.opportunities), "opportunity")
        _require_unique_ids((sat.id for sat in self.satellites), "satellite")
        _require_unique_ids((target.id for target in self.targets), "target")
        for opp in self.opportunities:
            _require_clean_id(opp.satellite_id, f"opportunity {opp.id} satellite_id")
            _require_clean_id(opp.target_id, f"opportunity {opp.id} target_id")
        _require_unique_ids(self.constraints.mandatory, "mandatory opportunity")
        for pair in self.constraints.mutually_exclusive:
            for endpoint in pair:
                _require_clean_id(endpoint, "mutual-exclusion endpoint")
        canonical_pairs = {tuple(sorted(pair)) for pair in self.constraints.mutually_exclusive}
        if len(canonical_pairs) != len(self.constraints.mutually_exclusive):
            raise ValueError("mutual-exclusion pairs must be unique")

    def _check_finite_values(self) -> None:
        for opp in self.opportunities:
            for field_name in (
                "mission_value",
                "duration_seconds",
                "energy_cost",
                "storage_cost",
                "pointing_cost",
            ):
                _require_finite(getattr(opp, field_name), f"opportunity {opp.id} {field_name}")
        for sat in self.satellites:
            _require_finite(sat.energy_capacity, f"satellite {sat.id} energy_capacity")
            _require_finite(sat.storage_capacity, f"satellite {sat.id} storage_capacity")
        _require_finite(self.objective.mission_value_weight, "mission_value_weight")
        if self.objective.penalty_coefficient is not None:
            _require_finite(self.objective.penalty_coefficient, "penalty_coefficient")
        if self.constraints.min_mission_value is not None:
            _require_finite(self.constraints.min_mission_value, "min_mission_value")


class RequestToProblemTranslation(BaseModel):
    """Result of deterministic request-to-problem translation."""

    model_config = ConfigDict(frozen=True)

    request_checksum: str
    source_mode: ObservationPlanningSourceMode
    problem: SchedulingProblem
    verification_label: PlanningVerificationLabel
    limitations: tuple[str, ...]


class ObservationPlanningScientificIdentity(BaseModel):
    """Deterministic identity for scientific comparison, excluding runtime metadata."""

    model_config = ConfigDict(frozen=True)

    request_checksum: str
    problem_checksum: str
    source_mode: ObservationPlanningSourceMode
    selected_solver: AuthoritativePlanningSolver | None
    selected_opportunity_ids: tuple[str, ...] | None
    status: PlanningResultStatus
    optimality_label: PlanningOptimalityLabel
    verification_label: PlanningVerificationLabel | None
    feasible: bool
    objective_value: float | None
    fallback_attempts: tuple[tuple[SolverKind, ExperimentStatus], ...] = ()


class ObservationPlanningResult(BaseModel):
    """Immutable in-memory result for authoritative classical observation planning."""

    model_config = ConfigDict(frozen=True)

    request_checksum: str
    problem_checksum: str = ""
    source_mode: ObservationPlanningSourceMode
    selected_solver: AuthoritativePlanningSolver | None = None
    solver_execution_status: ExperimentStatus | None = None
    status: PlanningResultStatus
    optimality_label: PlanningOptimalityLabel
    verification_label: PlanningVerificationLabel | None = None
    limitations: tuple[str, ...] = ()
    schedule: CandidateSchedule | None = None
    authoritative_result: SolverResult | None = None
    independent_evaluation: ScheduleEvaluation | None = None
    feasible: bool = False
    objective_value: float | None = None
    fallback_history: tuple[SolverResult, ...] = ()
    verification_errors: tuple[str, ...] = ()

    @property
    def scientific_identity(self) -> ObservationPlanningScientificIdentity:
        """Return the deterministic scientific identity, excluding runtime metadata."""

        return ObservationPlanningScientificIdentity(
            request_checksum=self.request_checksum,
            problem_checksum=self.problem_checksum,
            source_mode=self.source_mode,
            selected_solver=self.selected_solver,
            selected_opportunity_ids=(
                self.schedule.selected_opportunity_ids if self.schedule is not None else None
            ),
            status=self.status,
            optimality_label=self.optimality_label,
            verification_label=self.verification_label,
            feasible=self.feasible,
            objective_value=(
                self.independent_evaluation.objective_value
                if self.independent_evaluation is not None
                else None
            ),
            fallback_attempts=tuple(
                (attempt.solver_kind, attempt.status) for attempt in self.fallback_history
            ),
        )

    @model_validator(mode="after")
    def _check_consistency(self) -> ObservationPlanningResult:
        if (
            self.status != PlanningResultStatus.VERIFIED_FEASIBLE
            and self.optimality_label == PlanningOptimalityLabel.OPTIMAL
        ):
            raise ValueError("only verified-feasible results can be labelled optimal")
        if (
            self.status
            in {
                PlanningResultStatus.FAILED,
                PlanningResultStatus.INVALID,
                PlanningResultStatus.TIMED_OUT,
                PlanningResultStatus.UNSUPPORTED,
            }
            and self.optimality_label != PlanningOptimalityLabel.UNKNOWN
        ):
            raise ValueError("non-feasible non-success results require unknown optimality")
        if (
            self.status == PlanningResultStatus.INFEASIBLE
            and self.optimality_label != PlanningOptimalityLabel.INFEASIBLE
        ):
            raise ValueError("infeasible planning results must use the infeasible label")

        if self.status == PlanningResultStatus.INVALID:
            if self.feasible:
                raise ValueError("invalid planning results cannot be feasible")
            if self.authoritative_result is not None:
                raise ValueError("invalid planning results cannot carry solver evidence")
            return self

        if self.status == PlanningResultStatus.VERIFIED_FEASIBLE:
            if self.optimality_label not in {
                PlanningOptimalityLabel.OPTIMAL,
                PlanningOptimalityLabel.HEURISTIC,
            }:
                raise ValueError(
                    "verified-feasible results require optimal or heuristic optimality"
                )
            if not self.feasible:
                raise ValueError("verified-feasible results must set feasible=True")
            if self.independent_evaluation is None:
                raise ValueError("verified-feasible results require independent evaluation")
            if not self.independent_evaluation.feasible:
                raise ValueError("verified-feasible results require feasible evaluation")
            if self.schedule is None:
                raise ValueError("verified-feasible results require a schedule")
        elif self.feasible:
            raise ValueError("non-success planning results cannot set feasible=True")

        if self.authoritative_result is None:
            if self.status not in {
                PlanningResultStatus.INVALID,
                PlanningResultStatus.FAILED,
            }:
                raise ValueError("solver-backed planning results require authoritative evidence")
            return self

        if self.solver_execution_status != self.authoritative_result.status:
            raise ValueError("solver_execution_status must match authoritative result status")
        if self.authoritative_result.problem_checksum != self.problem_checksum:
            raise ValueError("authoritative result problem checksum must match planning result")
        if self.independent_evaluation is not None:
            if self.independent_evaluation.problem_checksum != self.problem_checksum:
                raise ValueError("evaluation problem checksum must match planning result")
            if self.objective_value is not None and not math.isclose(
                self.objective_value,
                self.independent_evaluation.objective_value,
                rel_tol=0.0,
                abs_tol=1e-9,
            ):
                raise ValueError("objective value must match independent evaluation")
        elif self.objective_value is not None:
            raise ValueError("objective value requires independent evaluation")

        if self.feasible and self.schedule is None:
            raise ValueError("feasible planning results require a schedule")

        if self.optimality_label == PlanningOptimalityLabel.OPTIMAL:
            if self.selected_solver != AuthoritativePlanningSolver.EXACT:
                raise ValueError("only exact planning results can be labelled optimal")
            if self.authoritative_result.optimality_status != OptimalityStatus.OPTIMAL:
                raise ValueError("optimal planning results require proven exact optimality")
        if (
            self.optimality_label == PlanningOptimalityLabel.HEURISTIC
            and self.selected_solver == AuthoritativePlanningSolver.EXACT
            and self.authoritative_result.optimality_status == OptimalityStatus.OPTIMAL
        ):
            raise ValueError("proven exact optimality cannot be labelled heuristic")

        if self.status == PlanningResultStatus.TIMED_OUT and (
            self.solver_execution_status != ExperimentStatus.TIMED_OUT or self.feasible
        ):
            raise ValueError("timed-out planning results must carry timed-out solver status")
        if self.status == PlanningResultStatus.UNSUPPORTED and (
            self.solver_execution_status != ExperimentStatus.UNSUPPORTED or self.feasible
        ):
            raise ValueError("unsupported planning results must carry unsupported solver status")
        if self.status == PlanningResultStatus.VERIFIED_FEASIBLE and (
            self.solver_execution_status != ExperimentStatus.COMPLETED
        ):
            raise ValueError("verified-feasible results require completed solver execution")

        return self


def _dt(value: object) -> str:
    if not isinstance(value, datetime):
        raise TypeError("expected datetime")
    return ensure_utc(value).isoformat()


def _require_clean_id(value: str, what: str) -> None:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{what} must be a non-empty, unpadded ID")


def _require_unique_ids(values: Iterable[str], what: str) -> None:
    ids = list(values)
    for value in ids:
        _require_clean_id(value, f"{what} ID")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{what} IDs must be unique")


def _require_finite(value: float, what: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{what} must be finite")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _dt(value)
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {
            str(k): _canonical_value(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(v) for v in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


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
            _canonical_value(opp) for opp in sorted(request.opportunities, key=lambda o: o.id)
        ],
        "satellites": [
            _canonical_value(sat) for sat in sorted(request.satellites, key=lambda s: s.id)
        ],
        "targets": [
            _canonical_value(target) for target in sorted(request.targets, key=lambda t: t.id)
        ],
        "constraints": _canonical_value(_canonical_constraints(request.constraints)),
        "objective": _canonical_value(request.objective),
        "limits": _canonical_value(request.limits),
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
        source_mode=request.source_mode,
        problem=normalized,
        verification_label=label,
        limitations=limitations,
    )
