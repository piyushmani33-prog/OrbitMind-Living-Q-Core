"""API wire schemas for read-only observation study chains.

This surface exposes authenticated traceability over persisted geometry-derived
eligibility and classical planning records. It does not recompute geometry,
derive eligibility, execute planning, or make operational claims.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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
from orbitmind.observation_studies.models import ObservationStudyChain

OBSERVATION_STUDY_DISCLAIMER = (
    "This is read-only authenticated traceability over pinned/offline geometry-derived "
    "eligibility and classical planning records. It does not prove live tracking, "
    "operational access, taskability, command readiness, approval, signed receipt status, "
    "or quantum authority."
)


class ObservationStudyGeometryResponse(BaseModel):
    """Safe geometry summary for an authenticated study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str
    run_id: str
    request_checksum: str
    geometry_checksum: str
    element_checksum: str
    source_identity_checksum: str
    satellite_id: str
    site_id: str
    sample_count: int
    failed_sample_count: int
    interval_count: int
    computation_version: str
    epistemic_status: EpistemicStatus
    limitations: tuple[str, ...]


class ObservationStudyEligibilityResponse(BaseModel):
    """Safe eligibility/provenance summary for an authenticated study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provenance_record_id: str
    provenance_checksum: str
    eligibility_set_id: str
    eligibility_set_checksum: str
    source_type: PinnedInputSourceType
    source_mode: PinnedInputSourceMode
    verification_status: ScientificInputVerificationStatus
    generation_rule_version: str | None
    window_count: int
    selected_window_ids: tuple[str, ...]
    selected_window_count: int
    limitations: tuple[str, ...]


class ObservationStudyPlanningResponse(BaseModel):
    """Safe planning/link summary for an authenticated study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    preparation_checksum: str
    planning_request_id: str
    planning_request_checksum: str
    planning_request_source_mode: ObservationPlanningSourceMode
    planning_run_id: str
    planning_scientific_identity_checksum: str
    observation_plan_id: str | None
    provenance_link_id: str
    link_checksum: str
    planning_status: PlanningResultStatus
    authoritative_solver: str | None
    optimality: PlanningOptimalityLabel
    feasible: bool
    objective_value: float | None
    limitations: tuple[str, ...]


class ObservationStudyCheckResponse(BaseModel):
    """One authenticated study-chain verification check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str
    passed: bool
    message: str


class ObservationStudyChainResponse(BaseModel):
    """Safe HTTP projection of an authenticated observation study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: str
    owner_id: str
    geometry: ObservationStudyGeometryResponse
    eligibility: ObservationStudyEligibilityResponse
    planning: ObservationStudyPlanningResponse
    checks: tuple[ObservationStudyCheckResponse, ...]
    limitations: tuple[str, ...]
    disclaimer: str = OBSERVATION_STUDY_DISCLAIMER

    @classmethod
    def from_chain(cls, chain: ObservationStudyChain) -> ObservationStudyChainResponse:
        return cls(
            schema_version=chain.schema_version,
            owner_id=chain.owner_id,
            geometry=ObservationStudyGeometryResponse(**chain.geometry.model_dump()),
            eligibility=ObservationStudyEligibilityResponse(
                provenance_record_id=chain.eligibility.provenance_record_id,
                provenance_checksum=chain.eligibility.provenance_checksum,
                eligibility_set_id=chain.eligibility.eligibility_set_record_id,
                eligibility_set_checksum=chain.eligibility.eligibility_set_checksum,
                source_type=chain.eligibility.source_type,
                source_mode=chain.eligibility.source_mode,
                verification_status=chain.eligibility.verification_status,
                generation_rule_version=chain.eligibility.generation_rule_version,
                window_count=chain.eligibility.window_count,
                selected_window_ids=chain.eligibility.selected_window_ids,
                selected_window_count=len(chain.eligibility.selected_window_ids),
                limitations=chain.eligibility.limitations,
            ),
            planning=ObservationStudyPlanningResponse(
                preparation_checksum=chain.planning.preparation_checksum,
                planning_request_id=chain.planning.planning_request_id,
                planning_request_checksum=chain.planning.planning_request_checksum,
                planning_request_source_mode=chain.planning.planning_request_source_mode,
                planning_run_id=chain.planning.planning_run_id,
                planning_scientific_identity_checksum=(
                    chain.planning.planning_scientific_identity_checksum
                ),
                observation_plan_id=chain.planning.observation_plan_id,
                provenance_link_id=chain.planning.link_record_id,
                link_checksum=chain.planning.link_checksum,
                planning_status=chain.planning.planning_status,
                authoritative_solver=chain.planning.authoritative_solver,
                optimality=chain.planning.optimality_label,
                feasible=chain.planning.feasible,
                objective_value=chain.planning.objective_value,
                limitations=chain.planning.limitations,
            ),
            checks=tuple(
                ObservationStudyCheckResponse(**check.model_dump()) for check in chain.checks
            ),
            limitations=chain.limitations,
        )
