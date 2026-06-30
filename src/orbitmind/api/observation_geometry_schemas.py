"""API wire schemas for read-only persisted observation geometry.

This surface exposes authenticated persisted summaries only. It does not compute geometry,
retrieve live orbit data, expose raw samples/intervals, claim taskability, approve commands,
or provide quantum authority.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

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
