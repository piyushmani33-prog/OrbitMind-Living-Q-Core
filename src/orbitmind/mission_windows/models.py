"""Immutable contracts for deterministic offline Earth-observer mission windows."""

from __future__ import annotations

import math
import re
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.timeutils import ensure_utc
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_geometry.models import (
    GEOMETRY_COMPUTATION_VERSION,
    PinnedOrbitElementSet,
)

MISSION_WINDOW_SCHEMA_VERSION: Literal["mission-window-v1"] = "mission-window-v1"
MISSION_WINDOW_ENGINE_VERSION: Literal["orbitmind-mission-window-1.0"] = (
    "orbitmind-mission-window-1.0"
)
MAX_MISSION_WINDOW_HORIZON_SECONDS = 86_400
MIN_COARSE_STEP_SECONDS = 5
MAX_COARSE_STEP_SECONDS = 300
MAX_COARSE_SAMPLES = 2_001
MAX_MISSION_WINDOWS = 256
MIN_OBSERVER_ALTITUDE_METRES = -500.0
MAX_OBSERVER_ALTITUDE_METRES = 9_000.0
MAX_OBSERVER_LABEL_LENGTH = 80
MAX_TRAJECTORY_REFERENCE_LENGTH = 240
EVENT_TIME_TOLERANCE_SECONDS = 0.1
PEAK_TIME_TOLERANCE_SECONDS = 0.1
MAX_CROSSING_REFINEMENT_ITERATIONS = 50
MAX_PEAK_REFINEMENT_ITERATIONS = 40
MAX_TOTAL_GEOMETRY_EVALUATIONS = 50_000

MODEL_STATEMENT: Literal[
    "Predicted from the identified orbital element set using the pinned propagation and "
    "geometry model."
] = (
    "Predicted from the identified orbital element set using the pinned propagation and "
    "geometry model."
)
GEOMETRIC_ONLY_LIMITATION = "Geometric window only; optical visibility is not assessed."
MISSION_WINDOW_LIMITATIONS: tuple[str, ...] = (
    MODEL_STATEMENT,
    GEOMETRIC_ONLY_LIMITATION,
    "Pinned orbital elements may be stale; prediction uncertainty depends on element age, "
    "object dynamics, maneuvers, drag, and modeling assumptions.",
    "TEME positions are rotated through the project Earth-fixed approximation; UT1 is "
    "approximated by UTC and no external Earth-orientation or polar-motion correction is used.",
    "No atmospheric refraction, terrain obstruction, weather, brightness, eclipse, twilight, "
    "RF link budget, or sensor constraint is assessed.",
    "Coarse sampling can miss an event that rises above and falls below the threshold entirely "
    "between adjacent samples; detected crossings and peaks are refined deterministically.",
    "Not live tracking and not suitable for command, maneuver, collision, safety, approval, or "
    "certification decisions.",
)

_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]*$")
_SAFE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:_-]*$")


class MissionWindowCalculationStatus(StrEnum):
    """Bounded calculation lifecycle represented by this result contract."""

    COMPLETED = "completed"


class MissionWindowEventClassification(StrEnum):
    """Whether a geometric window is complete or clipped by request boundaries."""

    COMPLETE = "complete"
    CLIPPED_AT_START = "clipped_at_start"
    CLIPPED_AT_END = "clipped_at_end"
    CLIPPED_AT_BOTH = "clipped_at_both"


class ObserverLocation(BaseModel):
    """One fixed WGS84 observer; no geocoding or terrain model is implied."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    altitude_metres: float = Field(
        default=0.0,
        ge=MIN_OBSERVER_ALTITUDE_METRES,
        le=MAX_OBSERVER_ALTITUDE_METRES,
    )
    label: str | None = Field(default=None, min_length=1, max_length=MAX_OBSERVER_LABEL_LENGTH)

    @model_validator(mode="after")
    def _validate_observer(self) -> ObserverLocation:
        _require_finite(self.latitude_deg, "observer latitude")
        _require_finite(self.longitude_deg, "observer longitude")
        _require_finite(self.altitude_metres, "observer altitude")
        if self.label is not None and _SAFE_LABEL.fullmatch(self.label) is None:
            raise ValueError("observer label must be a safe opaque label")
        return self


class MissionWindowRequest(BaseModel):
    """Bounded offline request over one pinned element set and one fixed observer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    orbital_source: PinnedOrbitElementSet
    trajectory_reference: str = Field(default="", max_length=MAX_TRAJECTORY_REFERENCE_LENGTH)
    observer: ObserverLocation
    start_time: datetime
    end_time: datetime
    minimum_elevation_deg: float = Field(ge=0.0, lt=90.0)
    coarse_step_seconds: int = Field(
        default=60,
        ge=MIN_COARSE_STEP_SECONDS,
        le=MAX_COARSE_STEP_SECONDS,
    )

    @model_validator(mode="after")
    def _validate_request(self) -> MissionWindowRequest:
        start = _normalize_utc(self.start_time, "start_time")
        end = _normalize_utc(self.end_time, "end_time")
        _require_finite(self.minimum_elevation_deg, "minimum_elevation_deg")
        if end <= start:
            raise ValueError("mission-window end_time must be after start_time")
        horizon_seconds = (end - start).total_seconds()
        if horizon_seconds > MAX_MISSION_WINDOW_HORIZON_SECONDS:
            raise ValueError("mission-window horizon must not exceed 24 hours")
        if self.expected_sample_count(start=start, end=end) > MAX_COARSE_SAMPLES:
            raise ValueError("mission-window request exceeds the coarse-sample bound")
        reference = self.trajectory_reference or (
            f"orbital-elements:{self.orbital_source.element_checksum}"
        )
        if (
            len(reference) > MAX_TRAJECTORY_REFERENCE_LENGTH
            or _OPAQUE_REFERENCE.fullmatch(reference) is None
        ):
            raise ValueError("trajectory_reference must be a bounded opaque reference")
        object.__setattr__(self, "start_time", start)
        object.__setattr__(self, "end_time", end)
        object.__setattr__(self, "trajectory_reference", reference)
        return self

    def expected_sample_count(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """Return the start/end-inclusive deterministic coarse-grid bound."""

        bounded_start = ensure_utc(start or self.start_time)
        bounded_end = ensure_utc(end or self.end_time)
        horizon = (bounded_end - bounded_start).total_seconds()
        return math.ceil(horizon / self.coarse_step_seconds) + 1

    @property
    def input_reference(self) -> str:
        return f"mission-window-input:{mission_window_request_checksum(self)}"


class MissionWindowEvent(BaseModel):
    """One positive-duration threshold window, possibly clipped to the request interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rise_time: datetime
    peak_time: datetime
    set_time: datetime
    rise_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    peak_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    set_azimuth_deg: float = Field(ge=0.0, lt=360.0)
    maximum_elevation_deg: float = Field(ge=-90.0, le=90.0)
    duration_seconds: float = Field(gt=0.0)
    classification: MissionWindowEventClassification
    begins_before_requested_interval: bool
    ends_after_requested_interval: bool

    @model_validator(mode="after")
    def _validate_event(self) -> MissionWindowEvent:
        rise = _normalize_utc(self.rise_time, "rise_time")
        peak = _normalize_utc(self.peak_time, "peak_time")
        set_time = _normalize_utc(self.set_time, "set_time")
        if set_time <= rise:
            raise ValueError("mission-window set_time must be after rise_time")
        if not rise <= peak <= set_time:
            raise ValueError("mission-window peak_time must be within its window")
        for value, name in (
            (self.rise_azimuth_deg, "rise_azimuth_deg"),
            (self.peak_azimuth_deg, "peak_azimuth_deg"),
            (self.set_azimuth_deg, "set_azimuth_deg"),
            (self.maximum_elevation_deg, "maximum_elevation_deg"),
            (self.duration_seconds, "duration_seconds"),
        ):
            _require_finite(value, name)
        expected_duration = (set_time - rise).total_seconds()
        if not math.isclose(self.duration_seconds, expected_duration, abs_tol=1e-6):
            raise ValueError("mission-window duration does not match its boundaries")
        expected_classification = classify_mission_window_event(
            self.begins_before_requested_interval,
            self.ends_after_requested_interval,
        )
        if self.classification is not expected_classification:
            raise ValueError("mission-window classification does not match clipping flags")
        object.__setattr__(self, "rise_time", rise)
        object.__setattr__(self, "peak_time", peak)
        object.__setattr__(self, "set_time", set_time)
        return self


class MissionWindowSourceIdentity(BaseModel):
    """Bounded identity and provenance summary for the pinned orbital source."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str = Field(min_length=1, max_length=160)
    object_name: str = Field(min_length=1, max_length=160)
    norad_catalog_id: int | None
    source_name: str = Field(min_length=1, max_length=500)
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    test_only: bool


class MissionWindowResult(BaseModel):
    """Deterministic geometric mission-window result with bounded claims."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["mission-window-v1"] = MISSION_WINDOW_SCHEMA_VERSION
    engine_version: Literal["orbitmind-mission-window-1.0"] = MISSION_WINDOW_ENGINE_VERSION
    source_identity: MissionWindowSourceIdentity
    trajectory_reference: str = Field(min_length=1, max_length=MAX_TRAJECTORY_REFERENCE_LENGTH)
    propagation_model: Literal["orbitmind-sgp4-wgs72-1.0"] = "orbitmind-sgp4-wgs72-1.0"
    geometry_model: Literal["orbitmind-look-angle-geometry-1.0"] = GEOMETRY_COMPUTATION_VERSION
    source_epoch: datetime | None
    request_start: datetime
    request_end: datetime
    observer: ObserverLocation
    minimum_elevation_deg: float = Field(ge=0.0, lt=90.0)
    coarse_step_seconds: int = Field(
        ge=MIN_COARSE_STEP_SECONDS,
        le=MAX_COARSE_STEP_SECONDS,
    )
    event_time_tolerance_seconds: float = EVENT_TIME_TOLERANCE_SECONDS
    peak_time_tolerance_seconds: float = PEAK_TIME_TOLERANCE_SECONDS
    prediction_start_offset_seconds: float | None
    prediction_end_offset_seconds: float | None
    windows: tuple[MissionWindowEvent, ...] = ()
    window_count: int = Field(ge=0, le=MAX_MISSION_WINDOWS)
    calculation_status: MissionWindowCalculationStatus = MissionWindowCalculationStatus.COMPLETED
    model_statement: str = MODEL_STATEMENT
    limitations: tuple[str, ...] = MISSION_WINDOW_LIMITATIONS
    input_reference: str = Field(pattern=r"^mission-window-input:[0-9a-f]{64}$")
    result_reference: str = ""
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION

    @model_validator(mode="after")
    def _validate_result(self) -> MissionWindowResult:
        request_start = _normalize_utc(self.request_start, "request_start")
        request_end = _normalize_utc(self.request_end, "request_end")
        source_epoch = (
            _normalize_utc(self.source_epoch, "source_epoch")
            if self.source_epoch is not None
            else None
        )
        if request_end <= request_start:
            raise ValueError("mission-window result request interval is invalid")
        if self.window_count != len(self.windows):
            raise ValueError("mission-window count must match windows")
        previous_set: datetime | None = None
        for event in self.windows:
            if event.rise_time < request_start or event.set_time > request_end:
                raise ValueError("mission window lies outside the request interval")
            if previous_set is not None and event.rise_time < previous_set:
                raise ValueError("mission windows must be ordered and non-overlapping")
            if event.maximum_elevation_deg < self.minimum_elevation_deg:
                raise ValueError("mission-window peak must meet the elevation threshold")
            previous_set = event.set_time
        if self.limitations != MISSION_WINDOW_LIMITATIONS:
            raise ValueError("mission-window result must retain the fixed limitation set")
        if self.model_statement != MODEL_STATEMENT:
            raise ValueError("mission-window model statement is fixed")
        for value, name in (
            (self.event_time_tolerance_seconds, "event_time_tolerance_seconds"),
            (self.peak_time_tolerance_seconds, "peak_time_tolerance_seconds"),
        ):
            _require_finite(value, name)
            if value <= 0.0:
                raise ValueError(f"{name} must be positive")
        for optional_value, name in (
            (self.prediction_start_offset_seconds, "prediction_start_offset_seconds"),
            (self.prediction_end_offset_seconds, "prediction_end_offset_seconds"),
        ):
            if optional_value is not None:
                _require_finite(optional_value, name)
        if source_epoch is None:
            if (
                self.prediction_start_offset_seconds is not None
                or self.prediction_end_offset_seconds is not None
            ):
                raise ValueError("prediction offsets require a source epoch")
        else:
            expected_start_offset = (request_start - source_epoch).total_seconds()
            expected_end_offset = (request_end - source_epoch).total_seconds()
            if self.prediction_start_offset_seconds != expected_start_offset:
                raise ValueError("prediction start offset does not match source epoch")
            if self.prediction_end_offset_seconds != expected_end_offset:
                raise ValueError("prediction end offset does not match source epoch")
        object.__setattr__(self, "request_start", request_start)
        object.__setattr__(self, "request_end", request_end)
        object.__setattr__(self, "source_epoch", source_epoch)
        expected_reference = f"mission-window-result:{mission_window_result_checksum(self)}"
        if self.result_reference and self.result_reference != expected_reference:
            raise ValueError("mission-window result reference does not match output")
        object.__setattr__(self, "result_reference", expected_reference)
        return self


def mission_window_request_checksum(request: MissionWindowRequest) -> str:
    """Return the deterministic identity of one normalized mission-window request."""

    return sha256_canonical_json(
        {
            "orbital_element_checksum": request.orbital_source.element_checksum,
            "trajectory_reference": request.trajectory_reference,
            "observer": request.observer.model_dump(mode="json"),
            "start_time": ensure_utc(request.start_time).isoformat(timespec="microseconds"),
            "end_time": ensure_utc(request.end_time).isoformat(timespec="microseconds"),
            "minimum_elevation_deg": round(request.minimum_elevation_deg, 9),
            "coarse_step_seconds": request.coarse_step_seconds,
        }
    )


def mission_window_result_checksum(result: MissionWindowResult) -> str:
    """Return a deterministic checksum over result content, excluding its own reference."""

    return sha256_canonical_json(
        result.model_dump(mode="json", exclude={"result_reference"}, round_trip=True)
    )


def classify_mission_window_event(
    begins_before: bool,
    ends_after: bool,
) -> MissionWindowEventClassification:
    if begins_before and ends_after:
        return MissionWindowEventClassification.CLIPPED_AT_BOTH
    if begins_before:
        return MissionWindowEventClassification.CLIPPED_AT_START
    if ends_after:
        return MissionWindowEventClassification.CLIPPED_AT_END
    return MissionWindowEventClassification.COMPLETE


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    try:
        return ensure_utc(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware") from exc


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")
