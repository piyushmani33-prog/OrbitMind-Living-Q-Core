"""Read-only integrity summaries for observation study chains."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from orbitmind.core.errors import ValidationError
from orbitmind.observation_studies.models import ObservationStudyChain
from orbitmind.observation_studies.queries import get_geometry_planning_study_chain

OBSERVATION_STUDY_CHAIN_INTEGRITY_STATUS: Literal["chain-checks-consistent"] = (
    "chain-checks-consistent"
)
OBSERVATION_STUDY_CHAIN_INTEGRITY_DISCLAIMER = (
    "This is read-only authenticated traceability over pinned/offline geometry-derived "
    "eligibility and classical planning records. It does not prove live tracking, "
    "operational access, taskability, command readiness, approval, signed receipt status, "
    "or quantum authority."
)
OBSERVATION_STUDY_CHAIN_INTEGRITY_LIMITATION = (
    "Authentication here means checksum and stored-record consistency of persisted records "
    "at read time. It is not real-world authenticity, operational access, approval, command "
    "readiness, taskability, or a signed receipt."
)


class ObservationStudyChainIntegrityCheckSummary(BaseModel):
    """One safe integrity-check summary from an authenticated study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    passed: bool
    details: str = Field(min_length=1, max_length=260)


class ObservationStudyChainIntegritySummary(BaseModel):
    """Success-only read-time integrity summary for an observation study chain."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner_id: str
    geometry_run_id: str
    geometry_run_checksum: str = Field(min_length=64, max_length=64)
    source_identity_checksum: str = Field(min_length=64, max_length=64)
    eligibility_set_id: str
    eligibility_set_checksum: str = Field(min_length=64, max_length=64)
    planning_request_id: str
    planning_run_id: str
    observation_plan_id: str | None
    provenance_link_id: str
    provenance_link_checksum: str = Field(min_length=64, max_length=64)
    status: Literal["chain-checks-consistent"] = OBSERVATION_STUDY_CHAIN_INTEGRITY_STATUS
    overall_passed: bool = True
    check_count: int
    failed_check_count: int = 0
    checks: tuple[ObservationStudyChainIntegrityCheckSummary, ...]
    limitations: tuple[str, ...]
    disclaimer: str = OBSERVATION_STUDY_CHAIN_INTEGRITY_DISCLAIMER


def summarize_geometry_planning_study_chain(
    session: Session,
    owner_id: str,
    *,
    geometry_run_id: str,
    provenance_link_id: str,
) -> ObservationStudyChainIntegritySummary:
    """Return a success-only integrity summary for an authenticated study chain.

    Failures from the underlying study-chain query propagate as typed errors. This function
    does not catch them, does not synthesize failed summaries, and performs no writes,
    geometry computation, eligibility derivation, or planning execution.
    """

    chain = get_geometry_planning_study_chain(
        session=session,
        owner_id=owner_id,
        geometry_run_id=geometry_run_id,
        provenance_link_id=provenance_link_id,
    )
    return _summary_from_chain(chain)


def _summary_from_chain(chain: ObservationStudyChain) -> ObservationStudyChainIntegritySummary:
    checks = tuple(
        ObservationStudyChainIntegrityCheckSummary(
            name=check.check_id,
            passed=check.passed,
            details=check.message,
        )
        for check in chain.checks
    )
    failed_check_count = sum(1 for check in checks if not check.passed)
    if failed_check_count:
        raise ValidationError("observation study chain integrity checks are inconsistent")

    return ObservationStudyChainIntegritySummary(
        owner_id=chain.owner_id,
        geometry_run_id=chain.geometry.run_id,
        geometry_run_checksum=chain.geometry.geometry_checksum,
        source_identity_checksum=chain.geometry.source_identity_checksum,
        eligibility_set_id=chain.eligibility.eligibility_set_record_id,
        eligibility_set_checksum=chain.eligibility.eligibility_set_checksum,
        planning_request_id=chain.planning.planning_request_id,
        planning_run_id=chain.planning.planning_run_id,
        observation_plan_id=chain.planning.observation_plan_id,
        provenance_link_id=chain.planning.link_record_id,
        provenance_link_checksum=chain.planning.link_checksum,
        check_count=len(checks),
        checks=checks,
        limitations=tuple(
            dict.fromkeys(
                (
                    *chain.limitations,
                    OBSERVATION_STUDY_CHAIN_INTEGRITY_LIMITATION,
                )
            )
        ),
    )
