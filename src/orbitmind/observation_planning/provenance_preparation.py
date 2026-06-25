"""Read-only preparation of planning requests from authenticated eligibility sets."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_planning.models import (
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    planning_request_checksum,
)
from orbitmind.observation_planning.provenance import (
    EligibilityWindow,
    EligibilityWindowSet,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
    eligibility_windows_to_opportunities,
    validate_request_against_eligibility,
)
from orbitmind.optimization.models import (
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    SchedulingProblemLimits,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
    StoredEligibilityWindowSet,
)
from orbitmind.persistence.observation_planning_repository import normalize_owner_id

PREPARATION_SCHEMA_VERSION: Literal["1"] = "1"
PREPARATION_DERIVATION_RULE = "eligibility-windows-to-declared-opportunities"
PREPARATION_DERIVATION_RULE_VERSION = "eligibility-planning-preparation-v1"
PREPARATION_LIMITATION = (
    "Prepared from authenticated fixture-backed or user-declared eligibility windows; "
    "no orbital access geometry, visibility, taskability, approval, command readiness, "
    "planning execution, or quantum authority is claimed."
)
_MAX_SELECTED_WINDOWS = 24


class PreparedEligibilityPlanningRequest(BaseModel):
    """Immutable read-only preparation envelope for an eligibility-backed request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = PREPARATION_SCHEMA_VERSION
    provenance_record_id: str
    provenance_checksum: str
    eligibility_set_record_id: str
    eligibility_set_checksum: str
    eligibility_source_type: PinnedInputSourceType
    eligibility_verification_status: ScientificInputVerificationStatus
    derivation_rule: str = PREPARATION_DERIVATION_RULE
    derivation_rule_version: str = PREPARATION_DERIVATION_RULE_VERSION
    prepared_request: ObservationPlanningRequest
    planning_request_checksum: str
    preparation_checksum: str = Field(min_length=64, max_length=64)
    selected_window_ids: tuple[str, ...]
    limitations: tuple[str, ...] = (PREPARATION_LIMITATION,)

    @model_validator(mode="after")
    def _check_checksum(self) -> PreparedEligibilityPlanningRequest:
        expected = preparation_checksum_for(
            provenance_checksum=self.provenance_checksum,
            eligibility_set_checksum=self.eligibility_set_checksum,
            selected_window_ids=self.selected_window_ids,
            derivation_rule=self.derivation_rule,
            derivation_rule_version=self.derivation_rule_version,
            planning_request_checksum=self.planning_request_checksum,
            limitations=self.limitations,
        )
        if expected != self.preparation_checksum:
            raise ValueError("preparation checksum mismatch")
        if self.planning_request_checksum != planning_request_checksum(self.prepared_request):
            raise ValueError("planning request checksum mismatch")
        return self


def prepare_eligibility_backed_planning_request(
    *,
    session: Session,
    owner_id: str,
    requested_by: str,
    eligibility_set_id: str | None = None,
    eligibility_set_checksum: str | None = None,
    selected_window_ids: Sequence[str] | None = None,
) -> PreparedEligibilityPlanningRequest:
    """Prepare a declared planning request from an authenticated eligibility-window set.

    This function is read-only. SQLAlchemy may open an implicit read transaction for the
    SELECTs, but this service performs no inserts, updates, deletes, commits, or rollbacks.
    """

    owner = normalize_owner_id(owner_id)
    requested_by_value = _clean_text(requested_by, "requested_by")
    stored_set = _load_window_set(
        SqlAlchemyObservationPlanningProvenanceRepository(session),
        owner_id=owner,
        eligibility_set_id=eligibility_set_id,
        eligibility_set_checksum=eligibility_set_checksum,
    )
    repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
    source = repo.get_provenance(stored_set.source_provenance_id, owner_id=owner)
    if source is None:
        raise ValidationError("eligibility source provenance missing")
    if source.provenance != stored_set.window_set.source_provenance:
        raise ValidationError("eligibility source provenance mismatch")
    if source.provenance_checksum != stored_set.window_set.source_provenance.checksum:
        raise ValidationError("eligibility source provenance checksum mismatch")

    selected_windows = _select_windows(stored_set.window_set.windows, selected_window_ids)
    if not selected_windows:
        raise ValidationError("eligibility-window set contains no windows to prepare")
    if len(selected_windows) > _MAX_SELECTED_WINDOWS:
        raise ValidationError("selected eligibility windows exceed planning variable bound")

    opportunities = _selected_opportunities(stored_set.window_set, selected_windows)
    request = _prepared_request(
        eligibility_set_checksum=stored_set.eligibility_set_checksum,
        requested_by=requested_by_value,
        windows=selected_windows,
        opportunities=opportunities,
    )
    validate_request_against_eligibility(request, stored_set.window_set)
    request_checksum = planning_request_checksum(request)
    selected_ids = tuple(window.id for window in selected_windows)
    limitations = tuple(dict.fromkeys((*stored_set.window_set.limitations, PREPARATION_LIMITATION)))
    checksum = preparation_checksum_for(
        provenance_checksum=source.provenance_checksum,
        eligibility_set_checksum=stored_set.eligibility_set_checksum,
        selected_window_ids=selected_ids,
        derivation_rule=PREPARATION_DERIVATION_RULE,
        derivation_rule_version=PREPARATION_DERIVATION_RULE_VERSION,
        planning_request_checksum=request_checksum,
        limitations=limitations,
    )
    return PreparedEligibilityPlanningRequest(
        provenance_record_id=source.id,
        provenance_checksum=source.provenance_checksum,
        eligibility_set_record_id=stored_set.id,
        eligibility_set_checksum=stored_set.eligibility_set_checksum,
        eligibility_source_type=source.provenance.source.source_type,
        eligibility_verification_status=source.provenance.verification_status,
        prepared_request=request,
        planning_request_checksum=request_checksum,
        preparation_checksum=checksum,
        selected_window_ids=selected_ids,
        limitations=limitations,
    )


def preparation_checksum_for(
    *,
    provenance_checksum: str,
    eligibility_set_checksum: str,
    selected_window_ids: tuple[str, ...],
    derivation_rule: str,
    derivation_rule_version: str,
    planning_request_checksum: str,
    limitations: tuple[str, ...],
) -> str:
    """Checksum the deterministic preparation identity, excluding database IDs."""

    return sha256_canonical_json(
        {
            "schema_version": PREPARATION_SCHEMA_VERSION,
            "provenance_checksum": provenance_checksum,
            "eligibility_set_checksum": eligibility_set_checksum,
            "selected_window_ids": list(selected_window_ids),
            "derivation_rule": derivation_rule,
            "derivation_rule_version": derivation_rule_version,
            "planning_request_checksum": planning_request_checksum,
            "limitations": list(limitations),
        }
    )


def _load_window_set(
    repo: SqlAlchemyObservationPlanningProvenanceRepository,
    *,
    owner_id: str,
    eligibility_set_id: str | None,
    eligibility_set_checksum: str | None,
) -> StoredEligibilityWindowSet:
    if (eligibility_set_id is None) == (eligibility_set_checksum is None):
        raise ValidationError("provide exactly one eligibility-set identifier or checksum")
    if eligibility_set_id is not None:
        stored = repo.get_eligibility_window_set(
            _clean_text(eligibility_set_id, "eligibility_set_id"),
            owner_id=owner_id,
        )
    else:
        stored = repo.get_eligibility_window_set_by_checksum(
            _clean_text(eligibility_set_checksum or "", "eligibility_set_checksum"),
            owner_id=owner_id,
        )
    if stored is None:
        raise NotFoundError("eligibility-window set not found")
    return stored


def _select_windows(
    windows: tuple[EligibilityWindow, ...],
    selected_window_ids: Sequence[str] | None,
) -> tuple[EligibilityWindow, ...]:
    if selected_window_ids is None:
        return windows
    selected_ids = tuple(_clean_text(value, "selected_window_id") for value in selected_window_ids)
    if not selected_ids:
        raise ValidationError("selected eligibility windows cannot be empty")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValidationError("selected eligibility window IDs must be unique")
    selected = set(selected_ids)
    windows_by_id = {window.id: window for window in windows}
    missing = sorted(selected - set(windows_by_id))
    if missing:
        raise ValidationError("selected eligibility window ID not found")
    return tuple(window for window in windows if window.id in selected)


def _selected_opportunities(
    window_set: EligibilityWindowSet,
    selected_windows: tuple[EligibilityWindow, ...],
) -> tuple[ObservationOpportunity, ...]:
    opportunities = eligibility_windows_to_opportunities(window_set)
    by_window_id = {
        opportunity.id.removeprefix("eligibility-"): opportunity for opportunity in opportunities
    }
    return tuple(by_window_id[window.id] for window in selected_windows)


def _prepared_request(
    *,
    eligibility_set_checksum: str,
    requested_by: str,
    windows: tuple[EligibilityWindow, ...],
    opportunities: tuple[ObservationOpportunity, ...],
) -> ObservationPlanningRequest:
    start = min(window.start for window in windows)
    end = max(window.end for window in windows)
    return ObservationPlanningRequest(
        name=f"eligibility-backed observation planning {eligibility_set_checksum[:12]}",
        horizon=PlanningHorizon(start=start, end=end),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=opportunities,
        satellites=_satellites(opportunities),
        targets=_targets(windows),
        limits=SchedulingProblemLimits(max_variables=24, exact_max_variables=22),
        requested_by=requested_by,
    )


def _satellites(opportunities: tuple[ObservationOpportunity, ...]) -> tuple[SatelliteResource, ...]:
    satellites: list[SatelliteResource] = []
    for asset_id in sorted({opportunity.satellite_id for opportunity in opportunities}):
        asset_opportunities = [
            opportunity for opportunity in opportunities if opportunity.satellite_id == asset_id
        ]
        satellites.append(
            SatelliteResource(
                id=asset_id,
                energy_capacity=sum(opportunity.energy_cost for opportunity in asset_opportunities),
                storage_capacity=sum(
                    opportunity.storage_cost for opportunity in asset_opportunities
                ),
            )
        )
    return tuple(satellites)


def _targets(windows: tuple[EligibilityWindow, ...]) -> tuple[ObservationTarget, ...]:
    return tuple(
        ObservationTarget(id=target_id) for target_id in sorted({w.target_id for w in windows})
    )


def _clean_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValidationError(f"{field_name} must be non-empty and unpadded")
    return value
