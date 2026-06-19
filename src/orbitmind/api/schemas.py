"""API wire schemas (separate from domain and ORM models).

Requests are parsed here and converted to domain models; responses embed the
already-typed domain models to avoid duplication while keeping a stable wire shape.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from orbitmind.governance.audit import AuditEvent
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.governance.provenance import ProvenanceRecord
from orbitmind.mission.models import (
    MissionRequest,
    MissionSource,
    MissionStatus,
    Observer,
    OutputType,
)
from orbitmind.sources.models import MissionSourceData
from orbitmind.space.models import OrbitalSourceRecord, OrbitalStateSample
from orbitmind.verification.models import VerificationFinding
from orbitmind.visualization.models import ArtifactRecord

SAMPLE_DATA_DISCLAIMER = (
    "Results are derived from bundled, stale sample TLE data for demonstration only. "
    "They are a deterministic calculation, NOT live satellite tracking data."
)


class OrbitPropagationRequest(BaseModel):
    """Wire request for an orbit-propagation mission."""

    satellite_id: str = Field(min_length=1, max_length=64, examples=["ISS"])
    start_time: datetime = Field(examples=["2019-12-09T17:00:00Z"])
    end_time: datetime = Field(examples=["2019-12-09T18:30:00Z"])
    step_seconds: int = Field(gt=0, examples=[60])
    observer_latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    observer_longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    observer_altitude_km: float | None = Field(default=None, ge=-0.5, le=9.0)
    output_types: list[OutputType] | None = None
    # Default stays "sample" (offline). "celestrak" requires network + source enabled.
    source: MissionSource = MissionSource.SAMPLE
    allow_sample_fallback: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> OrbitPropagationRequest:
        if self.start_time.tzinfo is None or self.end_time.tzinfo is None:
            raise ValueError("start_time and end_time must include a timezone (use UTC, e.g. ...Z)")
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time")
        return self

    def to_domain(self) -> MissionRequest:
        observer = None
        if self.observer_latitude is not None and self.observer_longitude is not None:
            observer = Observer(
                latitude_deg=self.observer_latitude,
                longitude_deg=self.observer_longitude,
                altitude_km=self.observer_altitude_km or 0.0,
            )
        outputs = self.output_types if self.output_types else list(OutputType)
        return MissionRequest(
            satellite_id=self.satellite_id,
            start_time=self.start_time,
            end_time=self.end_time,
            step_seconds=self.step_seconds,
            observer=observer,
            output_types=outputs,
            source=self.source,
            allow_sample_fallback=self.allow_sample_fallback,
        )


class MissionSummaryResponse(BaseModel):
    """Compact mission record for list/submit responses."""

    mission_id: str
    satellite_id: str
    status: MissionStatus
    epistemic_status: EpistemicStatus
    created_at: datetime
    completed_at: datetime | None
    request: MissionRequest
    disclaimer: str = SAMPLE_DATA_DISCLAIMER


class MissionDetailResponse(MissionSummaryResponse):
    """Full mission record including results, provenance, and artifacts."""

    source: OrbitalSourceRecord | None
    source_data: MissionSourceData | None
    units: dict[str, str]
    summary: dict[str, float]
    sample_count: int
    samples: list[OrbitalStateSample]
    findings: list[VerificationFinding]
    provenance: list[ProvenanceRecord]
    artifacts: list[ArtifactRecord]
    audit: list[AuditEvent]


class MissionListResponse(BaseModel):
    """Paginated list of missions."""

    total: int
    limit: int
    offset: int
    items: list[MissionSummaryResponse]


class ArtifactsResponse(BaseModel):
    """Artifacts for a single mission."""

    mission_id: str
    artifacts: list[ArtifactRecord]


class SourceSummaryResponse(BaseModel):
    """Compact view of a registered source."""

    source_id: str
    name: str
    kind: str
    description: str
    enabled: bool
    network_enabled: bool


class SourceCacheView(BaseModel):
    """Sanitized cache-entry metadata (no internal filesystem path exposed)."""

    cache_key: str
    source_id: str
    url: str
    checksum: str
    schema_version: str
    http_status: int
    content_type: str
    fetched_at: datetime
    expires_at: datetime
    effective_epoch: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    failure_reason: str | None


class SourceCacheResponse(BaseModel):
    """Cache entries for a source."""

    source_id: str
    entries: list[SourceCacheView]


class RefreshResultResponse(BaseModel):
    """Outcome of an explicit refresh (local-development-only endpoint)."""

    source_id: str
    satellite_id: str
    outcome: str  # fetched | cached | suppressed | failed | disabled
    freshness_state: str | None = None
    message: str


class ErrorResponse(BaseModel):
    """Safe error payload (no internal detail, SR-17)."""

    code: str
    message: str
