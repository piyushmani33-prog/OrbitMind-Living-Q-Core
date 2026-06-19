"""Mission domain models.

These are domain models (separate from the API wire schemas in ``api.schemas`` and
the ORM models in ``persistence.models``). Static field validation lives here;
settings-dependent bounds are enforced by ``mission.validation``.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import ensure_utc, utcnow
from orbitmind.governance.epistemic import EpistemicStatus


class MissionStatus(StrEnum):
    """Lifecycle state of a mission."""

    RECEIVED = "received"
    VALIDATED = "validated"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OutputType(StrEnum):
    """Supported visual output artifact types."""

    ALTITUDE_VS_TIME = "altitude_vs_time"
    GROUND_TRACK = "ground_track"


class MissionSource(StrEnum):
    """Where a mission obtains its orbital elements (decoupled from the sources module)."""

    SAMPLE = "sample"  # bundled offline fixture (default)
    CELESTRAK = "celestrak"  # CelesTrak GP (Phase 2; requires network + source enabled)


class Observer(BaseModel):
    """Optional ground observer location (geodetic)."""

    model_config = ConfigDict(frozen=True)

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    altitude_km: float = Field(default=0.0, ge=-0.5, le=9.0)


class MissionRequest(BaseModel):
    """A validated, normalized orbital mission request (domain model)."""

    model_config = ConfigDict(frozen=True)

    satellite_id: str = Field(min_length=1, max_length=64)
    start_time: datetime
    end_time: datetime
    step_seconds: int = Field(gt=0)
    observer: Observer | None = None
    output_types: list[OutputType] = Field(default_factory=lambda: list(OutputType))
    source: MissionSource = MissionSource.SAMPLE
    # Default: NO silent fallback. A CelesTrak mission only falls back to the bundled
    # sample if the caller explicitly opts in (and the result is labelled accordingly).
    allow_sample_fallback: bool = False

    @model_validator(mode="after")
    def _check_window(self) -> MissionRequest:
        start = ensure_utc(self.start_time)
        end = ensure_utc(self.end_time)
        if end <= start:
            raise ValueError("end_time must be strictly after start_time")
        return self

    @property
    def duration_seconds(self) -> float:
        return (ensure_utc(self.end_time) - ensure_utc(self.start_time)).total_seconds()

    def expected_sample_count(self) -> int:
        """Number of samples for an inclusive start/stepped/inclusive-end window."""
        return int(self.duration_seconds // self.step_seconds) + 1


class Mission(BaseModel):
    """Mission aggregate root."""

    id: str = Field(default_factory=new_id)
    satellite_id: str
    status: MissionStatus = MissionStatus.RECEIVED
    raw_request: dict[str, Any]  # preserved verbatim (SR-03)
    normalized_request: MissionRequest
    epistemic_status: EpistemicStatus = EpistemicStatus.UNKNOWN
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
