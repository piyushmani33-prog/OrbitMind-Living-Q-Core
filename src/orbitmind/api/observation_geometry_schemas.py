"""API wire schemas for read-only persisted observation geometry.

This surface exposes authenticated persisted summaries only. It does not compute geometry,
retrieve live orbit data, expose raw samples/intervals, claim taskability, approve commands,
or provide quantum authority.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_geometry.queries import (
    ObservationGeometryRequestDetails,
    ObservationGeometryRequestSummary,
    ObservationGeometryRunDetails,
    ObservationGeometryRunSummary,
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
