"""API wire schemas for persisted observation geometry.

This surface exposes authenticated persisted geometry summaries and one bounded derivation
operation. It does not compute geometry in the API layer, retrieve live orbit data, claim
taskability, approve commands, or provide quantum authority.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, field_validator

from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_geometry.models import GeometrySampleStatus, VisibilityRefinementStatus
from orbitmind.observation_geometry.queries import (
    ObservationGeometryIntervalPage,
    ObservationGeometryIntervalSummary,
    ObservationGeometryRequestDetails,
    ObservationGeometryRequestSummary,
    ObservationGeometryRunDetails,
    ObservationGeometryRunSummary,
    ObservationGeometrySamplePage,
    ObservationGeometrySampleSummary,
)

OBSERVATION_GEOMETRY_DISCLAIMER = (
    "Persisted bounded observation geometry from pinned offline orbit elements. Results are "
    "deterministic model output, not live tracking, not taskability, not approval or command "
    "readiness, not a signed receipt, and not quantum-authoritative."
)
GEOMETRY_DERIVED_ELIGIBILITY_DISCLAIMER = (
    "Geometry-derived eligibility is deterministic model-derived visibility eligibility from "
    "pinned/offline observation-geometry computation. It is not live tracking, not operational "
    "access, not taskability, not command readiness, not approval, not a signed receipt, and not "
    "quantum-authoritative."
)

_MAX_ATTRIBUTION_LENGTH = 120


class _GeometryDerivedEligibilityResultView(Protocol):
    owner_id: str
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
    derivation_checksum: str
    derivation_rule_version: str
    derivation_label: str
    minimum_peak_elevation_deg: float | None
    window_count: int
    limitations: tuple[str, ...]

    @property
    def derived_source_type(self) -> object: ...

    @property
    def derived_source_mode(self) -> object: ...

    @property
    def derived_verification_status(self) -> object: ...


def _enum_value(value: object) -> str:
    candidate = getattr(value, "value", value)
    if not isinstance(candidate, str):
        raise TypeError("response enum-like value must be a string")
    return candidate


def _check_optional_clean_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if (
        not value
        or value.strip() != value
        or len(value) > _MAX_ATTRIBUTION_LENGTH
        or any(char in value for char in "\r\n\t")
    ):
        raise ValueError(f"{field_name} must be non-empty, unpadded, and bounded")
    return value


class GeometryPositionResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    latitude_deg: float
    longitude_deg: float
    altitude_km: float


class GeometrySiteResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    site_id: str
    name: str | None
    position: GeometryPositionResponse


class GeometryDerivedEligibilityRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    requested_by: str | None = Field(default=None, max_length=_MAX_ATTRIBUTION_LENGTH)
    derivation_label: str | None = Field(default=None, max_length=_MAX_ATTRIBUTION_LENGTH)
    minimum_peak_elevation_deg: StrictFloat | StrictInt | None = None

    @field_validator("requested_by")
    @classmethod
    def _validate_requested_by(cls, value: str | None) -> str | None:
        return _check_optional_clean_text(value, "requested_by")

    @field_validator("derivation_label")
    @classmethod
    def _validate_derivation_label(cls, value: str | None) -> str | None:
        return _check_optional_clean_text(value, "derivation_label")

    @field_validator("minimum_peak_elevation_deg")
    @classmethod
    def _validate_minimum_peak(
        cls,
        value: StrictFloat | StrictInt | None,
    ) -> float | None:
        if value is None:
            return None
        number = float(value)
        if not math.isfinite(number) or number < 0.0 or number >= 90.0:
            raise ValueError("minimum_peak_elevation_deg must be finite, >= 0, and < 90")
        return number

    def requested_by_for(self, owner_id: str) -> str:
        return self.requested_by if self.requested_by is not None else owner_id


class GeometryDerivedEligibilityResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    owner_id: str
    geometry_run_id: str
    geometry_request_id: str
    geometry_checksum: str
    geometry_request_checksum: str
    element_checksum: str
    source_identity_checksum: str
    provenance_record_id: str
    provenance_checksum: str
    eligibility_set_id: str
    eligibility_set_checksum: str
    derivation_checksum: str
    derivation_rule_version: str
    derivation_label: str
    minimum_peak_elevation_deg: float | None
    window_count: int
    provenance_created: bool
    provenance_reused: bool
    eligibility_set_created: bool
    eligibility_set_reused: bool
    derived_source_type: str
    derived_source_mode: str
    derived_verification_status: str
    limitations: tuple[str, ...]
    disclaimer: str = GEOMETRY_DERIVED_ELIGIBILITY_DISCLAIMER

    @classmethod
    def from_result(
        cls,
        result: _GeometryDerivedEligibilityResultView,
    ) -> GeometryDerivedEligibilityResponse:
        return cls(
            owner_id=result.owner_id,
            geometry_run_id=result.geometry_run_id,
            geometry_request_id=result.geometry_request_id,
            geometry_checksum=result.geometry_checksum,
            geometry_request_checksum=result.geometry_request_checksum,
            element_checksum=result.element_checksum,
            source_identity_checksum=result.source_identity_checksum,
            provenance_record_id=result.provenance_record_id,
            provenance_checksum=result.provenance_checksum,
            eligibility_set_id=result.eligibility_set_record_id,
            eligibility_set_checksum=result.eligibility_set_checksum,
            derivation_checksum=result.derivation_checksum,
            derivation_rule_version=result.derivation_rule_version,
            derivation_label=result.derivation_label,
            minimum_peak_elevation_deg=result.minimum_peak_elevation_deg,
            window_count=result.window_count,
            provenance_created=result.provenance_created,
            provenance_reused=not result.provenance_created,
            eligibility_set_created=result.eligibility_set_created,
            eligibility_set_reused=not result.eligibility_set_created,
            derived_source_type=_enum_value(result.derived_source_type),
            derived_source_mode=_enum_value(result.derived_source_mode),
            derived_verification_status=_enum_value(result.derived_verification_status),
            limitations=result.limitations,
        )


class ObservationGeometryRequestSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    request_checksum: str
    element_checksum: str
    source_identity_checksum: str
    site: GeometrySiteResponse
    start: dt.datetime
    end: dt.datetime
    step_seconds: int
    minimum_elevation_deg: float
    created_at: dt.datetime

    @classmethod
    def from_summary(
        cls,
        summary: ObservationGeometryRequestSummary,
    ) -> ObservationGeometryRequestSummaryResponse:
        return cls(
            id=summary.id,
            owner_id=summary.owner_id,
            request_checksum=summary.request_checksum,
            element_checksum=summary.element_checksum,
            source_identity_checksum=summary.source_identity_checksum,
            site=GeometrySiteResponse(
                site_id=summary.site.site_id,
                name=summary.site.name,
                position=GeometryPositionResponse(
                    latitude_deg=summary.site.position.latitude_deg,
                    longitude_deg=summary.site.position.longitude_deg,
                    altitude_km=summary.site.position.altitude_km,
                ),
            ),
            start=summary.start,
            end=summary.end,
            step_seconds=summary.step_seconds,
            minimum_elevation_deg=summary.minimum_elevation_deg,
            created_at=summary.created_at,
        )


class ObservationGeometryRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    request_checksum: str
    element_checksum: str
    source_identity_checksum: str
    site: GeometrySiteResponse
    start: dt.datetime
    end: dt.datetime
    step_seconds: int
    minimum_elevation_deg: float
    created_at: dt.datetime
    disclaimer: str = OBSERVATION_GEOMETRY_DISCLAIMER

    @classmethod
    def from_details(
        cls,
        details: ObservationGeometryRequestDetails,
    ) -> ObservationGeometryRequestResponse:
        summary = ObservationGeometryRequestSummaryResponse.from_summary(details.summary)
        return cls(**summary.model_dump())


class ObservationGeometryRunSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    geometry_checksum: str
    element_checksum: str
    source_identity_checksum: str
    sample_count: int
    failed_sample_count: int
    interval_count: int
    computation_version: str
    epistemic_status: EpistemicStatus
    limitations: tuple[str, ...]
    created_at: dt.datetime
    completed_at: dt.datetime

    @classmethod
    def from_summary(
        cls,
        summary: ObservationGeometryRunSummary,
    ) -> ObservationGeometryRunSummaryResponse:
        return cls(**summary.model_dump())


class ObservationGeometryRunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    geometry_checksum: str
    element_checksum: str
    source_identity_checksum: str
    sample_count: int
    failed_sample_count: int
    interval_count: int
    computation_version: str
    epistemic_status: EpistemicStatus
    limitations: tuple[str, ...]
    created_at: dt.datetime
    completed_at: dt.datetime
    disclaimer: str = OBSERVATION_GEOMETRY_DISCLAIMER

    @classmethod
    def from_details(cls, details: ObservationGeometryRunDetails) -> ObservationGeometryRunResponse:
        summary = ObservationGeometryRunSummaryResponse.from_summary(details.summary)
        return cls(**summary.model_dump())


class ObservationGeometryRequestListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationGeometryRequestSummaryResponse, ...]
    disclaimer: str = OBSERVATION_GEOMETRY_DISCLAIMER


class ObservationGeometryRunListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationGeometryRunSummaryResponse, ...]
    disclaimer: str = OBSERVATION_GEOMETRY_DISCLAIMER


class ObservationGeometrySampleResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence_index: int
    timestamp: dt.datetime
    status: GeometrySampleStatus
    azimuth_deg: float | None
    elevation_deg: float | None
    slant_range_km: float | None
    safe_error_code: str | None

    @classmethod
    def from_summary(
        cls,
        summary: ObservationGeometrySampleSummary,
    ) -> ObservationGeometrySampleResponse:
        return cls(**summary.model_dump())


class ObservationGeometryIntervalResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sequence_index: int
    rise_time: dt.datetime
    set_time: dt.datetime
    peak_time: dt.datetime
    peak_elevation_deg: float
    rise_azimuth_deg: float
    set_azimuth_deg: float
    rise_boundary_clipped: bool
    set_boundary_clipped: bool
    refinement_status: VisibilityRefinementStatus

    @classmethod
    def from_summary(
        cls,
        summary: ObservationGeometryIntervalSummary,
    ) -> ObservationGeometryIntervalResponse:
        return cls(**summary.model_dump())


class ObservationGeometrySampleListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    request_id: str
    geometry_checksum: str
    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationGeometrySampleResponse, ...]
    limitations: tuple[str, ...]
    disclaimer: str = OBSERVATION_GEOMETRY_DISCLAIMER

    @classmethod
    def from_page(
        cls,
        page: ObservationGeometrySamplePage,
    ) -> ObservationGeometrySampleListResponse:
        return cls(
            run_id=page.run_id,
            request_id=page.request_id,
            geometry_checksum=page.geometry_checksum,
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            has_next=page.has_next,
            items=tuple(
                ObservationGeometrySampleResponse.from_summary(item) for item in page.items
            ),
            limitations=page.limitations,
        )


class ObservationGeometryIntervalListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    request_id: str
    geometry_checksum: str
    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[ObservationGeometryIntervalResponse, ...]
    limitations: tuple[str, ...]
    disclaimer: str = OBSERVATION_GEOMETRY_DISCLAIMER

    @classmethod
    def from_page(
        cls,
        page: ObservationGeometryIntervalPage,
    ) -> ObservationGeometryIntervalListResponse:
        return cls(
            run_id=page.run_id,
            request_id=page.request_id,
            geometry_checksum=page.geometry_checksum,
            total=page.total,
            limit=page.limit,
            offset=page.offset,
            has_next=page.has_next,
            items=tuple(
                ObservationGeometryIntervalResponse.from_summary(item) for item in page.items
            ),
            limitations=page.limitations,
        )
