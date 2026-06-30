"""Derive Phase 4B eligibility sets from authenticated observation-geometry runs.

This module bridges persisted geometry model output to planning eligibility without
recomputing geometry, executing planning, or claiming operational access/taskability.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_geometry.models import ComputedVisibilityInterval
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    EligibilityWindow,
    EligibilityWindowSet,
    InputRightsDeclaration,
    InputRightsPermission,
    InputRightsStatus,
    InputSourceIdentity,
    PinnedInputArtifact,
    PinnedInputProvenance,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
)
from orbitmind.persistence.observation_planning_repository import normalize_owner_id

GEOMETRY_ELIGIBILITY_ADAPTER_SCHEMA_VERSION: Literal["1"] = "1"
GEOMETRY_ELIGIBILITY_DERIVATION_RULE = "geometry-visibility-intervals-to-eligibility"
GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION = "geometry-derived-eligibility-v1"
GEOMETRY_DERIVED_LIMITATION = (
    "Geometry-derived eligibility from pinned offline model output; not live tracking, "
    "taskability, approval, command readiness, signed receipt, or quantum authority."
)
GEOMETRY_DERIVED_ACCESS_LIMITATION = (
    "Visibility intervals are model-derived candidates and do not prove operational access or "
    "mission feasibility."
)
_DEFAULT_DERIVATION_LABEL = "geometry-derived-visibility"
_MAX_LABEL_LENGTH = 120
_MAX_GEOMETRY_DERIVED_WINDOWS = 24


class GeometryDerivedEligibilityResult(BaseModel):
    """Immutable result returned by the geometry-to-eligibility adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = GEOMETRY_ELIGIBILITY_ADAPTER_SCHEMA_VERSION
    owner_id: str
    requested_by: str
    geometry_run_id: str
    geometry_request_id: str
    geometry_checksum: str
    geometry_request_checksum: str
    element_checksum: str
    source_identity_checksum: str
    provenance_record_id: str
    provenance_checksum: str
    provenance_created: bool
    eligibility_set_record_id: str
    eligibility_set_checksum: str
    eligibility_set_created: bool
    derivation_checksum: str = Field(min_length=64, max_length=64)
    derivation_rule: str = GEOMETRY_ELIGIBILITY_DERIVATION_RULE
    derivation_rule_version: str = GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION
    derivation_label: str
    minimum_peak_elevation_deg: float | None = None
    window_count: int
    derived_source_type: PinnedInputSourceType
    derived_source_mode: PinnedInputSourceMode
    derived_verification_status: ScientificInputVerificationStatus
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def _check_result(self) -> GeometryDerivedEligibilityResult:
        if self.derived_source_type != PinnedInputSourceType.DERIVED:
            raise ValueError("geometry-derived eligibility must use derived source type")
        if self.derived_source_mode != PinnedInputSourceMode.DERIVED_FROM_GEOMETRY:
            raise ValueError("geometry-derived eligibility must use geometry-derived source mode")
        if self.derived_verification_status != ScientificInputVerificationStatus.GEOMETRY_DERIVED:
            raise ValueError("geometry-derived eligibility must use geometry-derived status")
        return self


def derive_eligibility_from_geometry_run(
    *,
    session: Session,
    owner_id: str,
    geometry_run_id: str,
    requested_by: str,
    derivation_label: str | None = None,
    minimum_peak_elevation_deg: float | None = None,
) -> GeometryDerivedEligibilityResult:
    """Create or replay a derived eligibility set from a persisted geometry run.

    The service owns one outer SQLAlchemy transaction. It authenticates persisted geometry
    through the geometry repository, then creates or reuses planning provenance and eligibility
    records. SQLAlchemy may open a database transaction for the enclosed reads/writes; callers
    should provide a fresh session with no active transaction.
    """

    if session.in_transaction():
        raise ValidationError("geometry-derived eligibility requires a fresh session")
    owner = normalize_owner_id(owner_id)
    run_id = _clean_text(geometry_run_id, "geometry_run_id")
    requested_by_value = _clean_text(requested_by, "requested_by")
    label = _clean_text(
        derivation_label if derivation_label is not None else _DEFAULT_DERIVATION_LABEL,
        "derivation_label",
    )
    peak_filter = _normalize_peak_filter(minimum_peak_elevation_deg)
    use_savepoint = _repository_savepoints_enabled(session)

    with session.begin():
        geometry_repository = SqlAlchemyObservationGeometryRepository(session)
        stored_run = geometry_repository.get_geometry_run(run_id, owner_id=owner)
        if stored_run is None:
            raise NotFoundError("observation-geometry run not found")
        stored_request = geometry_repository.get_geometry_request(
            stored_run.request_id,
            owner_id=owner,
        )
        if stored_request is None:
            raise ValidationError("observation-geometry run request relationship mismatch")

        intervals = _selected_intervals(stored_run.result.intervals, peak_filter)
        if len(intervals) > _MAX_GEOMETRY_DERIVED_WINDOWS:
            raise ValidationError("geometry-derived eligibility exceeds planning variable bound")

        interval_payloads = tuple(
            _interval_payload(index, interval) for index, interval in enumerate(intervals)
        )
        derivation_limitations = (GEOMETRY_DERIVED_LIMITATION, GEOMETRY_DERIVED_ACCESS_LIMITATION)
        derivation_checksum = geometry_eligibility_derivation_checksum_for(
            geometry_checksum=stored_run.geometry_checksum,
            request_checksum=stored_run.request_checksum,
            element_checksum=stored_request.element_checksum,
            source_identity_checksum=stored_request.source_identity_checksum,
            interval_payloads=interval_payloads,
            derivation_label=label,
            minimum_peak_elevation_deg=peak_filter,
            limitations=derivation_limitations,
        )
        provenance = _derived_provenance(
            geometry_checksum=stored_run.geometry_checksum,
            request_checksum=stored_run.request_checksum,
            element_checksum=stored_request.element_checksum,
            source_identity_checksum=stored_request.source_identity_checksum,
            derivation_checksum=derivation_checksum,
            derivation_label=label,
            minimum_peak_elevation_deg=peak_filter,
            interval_payloads=interval_payloads,
            effective_start=stored_request.request.start,
            effective_end=stored_request.request.end,
            limitations=derivation_limitations,
        )
        windows = tuple(
            _eligibility_window(
                interval=interval,
                interval_index=index,
                provenance_checksum=provenance.checksum,
                asset_id=stored_request.request.elements.source.satellite_id,
                target_id=stored_request.request.site.site_id,
                limitations=derivation_limitations,
            )
            for index, interval in enumerate(intervals)
        )
        window_set = EligibilityWindowSet(
            source_provenance=provenance,
            windows=windows,
            generation_rule_version=GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION,
            limitations=derivation_limitations,
        )

        planning_repository = SqlAlchemyObservationPlanningProvenanceRepository(session)
        existing_provenance = planning_repository.get_provenance_by_checksum(
            provenance.checksum,
            owner_id=owner,
        )
        stored_provenance = planning_repository.create_provenance(
            provenance,
            owner_id=owner,
            use_savepoint=use_savepoint,
        )
        existing_set = planning_repository.get_eligibility_window_set_by_checksum(
            window_set.checksum,
            owner_id=owner,
        )
        stored_set = planning_repository.create_eligibility_window_set(
            window_set,
            owner_id=owner,
            use_savepoint=use_savepoint,
        )

        return GeometryDerivedEligibilityResult(
            owner_id=owner,
            requested_by=requested_by_value,
            geometry_run_id=stored_run.id,
            geometry_request_id=stored_request.id,
            geometry_checksum=stored_run.geometry_checksum,
            geometry_request_checksum=stored_run.request_checksum,
            element_checksum=stored_request.element_checksum,
            source_identity_checksum=stored_request.source_identity_checksum,
            provenance_record_id=stored_provenance.id,
            provenance_checksum=stored_provenance.provenance_checksum,
            provenance_created=existing_provenance is None,
            eligibility_set_record_id=stored_set.id,
            eligibility_set_checksum=stored_set.eligibility_set_checksum,
            eligibility_set_created=existing_set is None,
            derivation_checksum=derivation_checksum,
            derivation_label=label,
            minimum_peak_elevation_deg=peak_filter,
            window_count=len(stored_set.window_set.windows),
            derived_source_type=stored_provenance.provenance.source.source_type,
            derived_source_mode=stored_provenance.provenance.source.source_mode,
            derived_verification_status=stored_provenance.provenance.verification_status,
            limitations=derivation_limitations,
        )


def geometry_eligibility_derivation_checksum_for(
    *,
    geometry_checksum: str,
    request_checksum: str,
    element_checksum: str,
    source_identity_checksum: str,
    interval_payloads: tuple[dict[str, Any], ...],
    derivation_label: str,
    minimum_peak_elevation_deg: float | None,
    limitations: tuple[str, ...],
) -> str:
    """Checksum the deterministic geometry-to-eligibility derivation identity."""

    return sha256_canonical_json(
        {
            "schema_version": GEOMETRY_ELIGIBILITY_ADAPTER_SCHEMA_VERSION,
            "derivation_rule": GEOMETRY_ELIGIBILITY_DERIVATION_RULE,
            "derivation_rule_version": GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION,
            "derivation_label": derivation_label,
            "minimum_peak_elevation_deg": minimum_peak_elevation_deg,
            "geometry_checksum": geometry_checksum,
            "request_checksum": request_checksum,
            "element_checksum": element_checksum,
            "source_identity_checksum": source_identity_checksum,
            "intervals": list(interval_payloads),
            "limitations": list(limitations),
        }
    )


def _derived_provenance(
    *,
    geometry_checksum: str,
    request_checksum: str,
    element_checksum: str,
    source_identity_checksum: str,
    derivation_checksum: str,
    derivation_label: str,
    minimum_peak_elevation_deg: float | None,
    interval_payloads: tuple[dict[str, Any], ...],
    effective_start: datetime,
    effective_end: datetime,
    limitations: tuple[str, ...],
) -> PinnedInputProvenance:
    artifact_payload = {
        "schema_version": GEOMETRY_ELIGIBILITY_ADAPTER_SCHEMA_VERSION,
        "derivation_rule": GEOMETRY_ELIGIBILITY_DERIVATION_RULE,
        "derivation_rule_version": GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION,
        "derivation_checksum": derivation_checksum,
        "derivation_label": derivation_label,
        "minimum_peak_elevation_deg": minimum_peak_elevation_deg,
        "geometry_checksum": geometry_checksum,
        "request_checksum": request_checksum,
        "element_checksum": element_checksum,
        "source_identity_checksum": source_identity_checksum,
        "intervals": list(interval_payloads),
        "limitations": list(limitations),
    }
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"geometry-source:{source_identity_checksum}",
            source_type=PinnedInputSourceType.DERIVED,
            source_mode=PinnedInputSourceMode.DERIVED_FROM_GEOMETRY,
            publisher="OrbitMind",
            dataset_name="geometry-derived-eligibility",
            dataset_version=GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION,
            dataset_revision=f"geometry:{geometry_checksum}",
        ),
        artifact=PinnedInputArtifact(
            artifact_id=f"geometry-derived-eligibility-{derivation_checksum[:24]}",
            content_checksum=sha256_canonical_json(artifact_payload),
            media_type="application/vnd.orbitmind.geometry-derived-eligibility+json",
            record_count=len(interval_payloads),
        ),
        effective_start=effective_start,
        effective_end=effective_end,
        rights=InputRightsDeclaration(
            rights_status=InputRightsStatus.DECLARED,
            redistribution=InputRightsPermission.UNKNOWN,
            commercial_use=InputRightsPermission.UNKNOWN,
            attribution_required=None,
            user_responsibility="caller remains responsible for downstream use of derived input",
            limitations=("geometry-derived rights record only",),
        ),
        verification_status=ScientificInputVerificationStatus.GEOMETRY_DERIVED,
        parent_provenance_checksums=(),
        limitations=limitations,
    )


def _eligibility_window(
    *,
    interval: ComputedVisibilityInterval,
    interval_index: int,
    provenance_checksum: str,
    asset_id: str,
    target_id: str,
    limitations: tuple[str, ...],
) -> EligibilityWindow:
    if interval.set_time <= interval.rise_time:
        raise ValidationError("geometry-derived eligibility interval must have positive duration")
    window_payload = _interval_payload(interval_index, interval)
    window_hash = sha256_canonical_json(window_payload)[:16]
    return EligibilityWindow(
        id=f"geometry-{interval_index:04d}-{window_hash}",
        asset_id=asset_id,
        target_id=target_id,
        start=interval.rise_time,
        end=interval.set_time,
        source_provenance_checksum=provenance_checksum,
        declaration_mode=EligibilityDeclarationMode.DERIVED_FROM_GEOMETRY,
        eligibility_reason="geometry-derived-visibility",
        verification_status=ScientificInputVerificationStatus.GEOMETRY_DERIVED,
        limitations=limitations,
    )


def _selected_intervals(
    intervals: tuple[ComputedVisibilityInterval, ...],
    minimum_peak_elevation_deg: float | None,
) -> tuple[ComputedVisibilityInterval, ...]:
    selected: list[ComputedVisibilityInterval] = []
    for interval in intervals:
        if interval.set_time <= interval.rise_time:
            raise ValidationError("geometry visibility interval must have positive duration")
        if (
            minimum_peak_elevation_deg is not None
            and interval.peak_elevation_deg < minimum_peak_elevation_deg
        ):
            continue
        selected.append(interval)
    return tuple(selected)


def _interval_payload(index: int, interval: ComputedVisibilityInterval) -> dict[str, Any]:
    return {
        "sequence_index": index,
        "rise_time": interval.rise_time.isoformat(),
        "set_time": interval.set_time.isoformat(),
        "peak_time": interval.peak_time.isoformat(),
        "peak_elevation_deg": _round_float(interval.peak_elevation_deg),
        "rise_azimuth_deg": _round_float(interval.rise_azimuth_deg),
        "set_azimuth_deg": _round_float(interval.set_azimuth_deg),
        "rise_boundary_clipped": interval.rise_boundary_clipped,
        "set_boundary_clipped": interval.set_boundary_clipped,
        "refinement_status": interval.refinement_status.value,
    }


def _normalize_peak_filter(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value) or value < 0.0 or value >= 90.0:
        raise ValidationError("minimum_peak_elevation_deg must be finite, >= 0, and < 90")
    return _round_float(value)


def _round_float(value: float) -> float:
    return round(float(value), 12)


def _clean_text(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > _MAX_LABEL_LENGTH
        or any(char in value for char in "\r\n\t")
    ):
        raise ValidationError(f"{field_name} must be non-empty, unpadded, and bounded")
    return value


def _repository_savepoints_enabled(session: Session) -> bool:
    return session.get_bind().dialect.name != "sqlite"
