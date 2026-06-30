"""Strict read models for authenticated observation study chains."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_planning.models import (
    ObservationPlanningSourceMode,
    PlanningOptimalityLabel,
    PlanningResultStatus,
)
from orbitmind.observation_planning.provenance import (
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)

OBSERVATION_STUDY_SCHEMA_VERSION: Literal["1"] = "1"
OBSERVATION_STUDY_LIMITATION = (
    "Observation study chain is read-only authenticated traceability over pinned/offline "
    "geometry-derived eligibility and classical planning records; it does not prove live "
    "tracking, operational access, taskability, command readiness, approval, signed receipt "
    "status, or quantum authority."
)


class ObservationStudyCheck(BaseModel):
    """One authenticated read-model check for an observation study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str = Field(min_length=1, max_length=120)
    passed: bool = True
    message: str = Field(min_length=1, max_length=260)


class GeometryStudySummary(BaseModel):
    """Safe authenticated geometry side of a study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    run_id: str
    request_checksum: str = Field(min_length=64, max_length=64)
    geometry_checksum: str = Field(min_length=64, max_length=64)
    element_checksum: str = Field(min_length=64, max_length=64)
    source_identity_checksum: str = Field(min_length=64, max_length=64)
    satellite_id: str
    site_id: str
    sample_count: int
    failed_sample_count: int
    interval_count: int
    computation_version: str
    epistemic_status: EpistemicStatus
    limitations: tuple[str, ...]


class StudyEligibilitySummary(BaseModel):
    """Safe authenticated eligibility/provenance side of a study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance_record_id: str
    provenance_checksum: str = Field(min_length=64, max_length=64)
    eligibility_set_record_id: str
    eligibility_set_checksum: str = Field(min_length=64, max_length=64)
    source_type: PinnedInputSourceType
    source_mode: PinnedInputSourceMode
    verification_status: ScientificInputVerificationStatus
    generation_rule_version: str | None
    window_count: int
    selected_window_ids: tuple[str, ...]
    limitations: tuple[str, ...]


class PlanningStudySummary(BaseModel):
    """Safe authenticated planning/link side of a study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preparation_checksum: str = Field(min_length=64, max_length=64)
    planning_request_id: str
    planning_request_checksum: str = Field(min_length=64, max_length=64)
    planning_request_source_mode: ObservationPlanningSourceMode
    planning_run_id: str
    planning_scientific_identity_checksum: str = Field(min_length=64, max_length=64)
    observation_plan_id: str | None
    link_record_id: str
    link_checksum: str = Field(min_length=64, max_length=64)
    planning_status: PlanningResultStatus
    authoritative_solver: str | None
    optimality_label: PlanningOptimalityLabel
    feasible: bool
    objective_value: float | None
    limitations: tuple[str, ...]


class ObservationStudyChain(BaseModel):
    """Authenticated geometry-to-planning study chain read model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = OBSERVATION_STUDY_SCHEMA_VERSION
    owner_id: str
    geometry: GeometryStudySummary
    eligibility: StudyEligibilitySummary
    planning: PlanningStudySummary
    checks: tuple[ObservationStudyCheck, ...]
    limitations: tuple[str, ...] = (OBSERVATION_STUDY_LIMITATION,)
