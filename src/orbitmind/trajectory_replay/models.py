"""Immutable contracts for deterministic offline Earth-orbit trajectory replay."""

from __future__ import annotations

import math
import re
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.timeutils import ensure_utc
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_geometry.models import GeodeticPosition, PinnedOrbitElementSet
from orbitmind.space.propagation import COMPUTATION_VERSION

TRAJECTORY_REPLAY_SCHEMA_VERSION: Literal["trajectory-replay-v1"] = "trajectory-replay-v1"
TRAJECTORY_REPLAY_ENGINE_VERSION: Literal["orbitmind-trajectory-replay-1.0"] = (
    "orbitmind-trajectory-replay-1.0"
)
FRAME_GEODETIC_MODEL_VERSION: Literal["orbitmind-teme-gmst-pef-wgs84-1.0"] = (
    "orbitmind-teme-gmst-pef-wgs84-1.0"
)
OBSERVER_GEOMETRY_MODEL_VERSION: Literal["orbitmind-look-angle-geometry-1.0"] = (
    "orbitmind-look-angle-geometry-1.0"
)
MAX_REPLAY_DURATION_SECONDS = 86_400
MIN_REPLAY_SAMPLE_INTERVAL_SECONDS = 1
MAX_REPLAY_SAMPLE_INTERVAL_SECONDS = 300
MAX_REPLAY_SAMPLES = 2_001
MAX_TRAJECTORY_REFERENCE_LENGTH = 240

PREDICTED_REPLAY_LIMITATION = "Predicted trajectory replay; not live tracking."
PINNED_MODEL_STATEMENT = (
    "Predicted from the identified orbital element set using the pinned propagation and "
    "geometry model."
)
TRAJECTORY_REPLAY_LIMITATIONS: tuple[str, ...] = (
    PREDICTED_REPLAY_LIMITATION,
    PINNED_MODEL_STATEMENT,
    "Pinned orbital elements may be stale; prediction usefulness depends on element age, "
    "object dynamics, maneuvers, drag, and modeling assumptions.",
    "TEME positions are rotated through the project GMST Earth-fixed approximation; UTC is "
    "used as a UT1 approximation and no external Earth-orientation or polar-motion correction "
    "is applied.",
    "Latitude is WGS84 geodetic latitude, longitude is canonical [-180, 180) degrees, and "
    "altitude is relative to the WGS84 ellipsoid.",
    "The output is a model prediction rather than a true current state; no universal position-"
    "error percentage or kilometre guarantee is provided.",
    "No optical visibility, terrain, weather, collision, maneuver, command, safety, approval, "
    "or certification authority is provided.",
)

_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]*$")
_SAFE_OBJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]*$")
_SAFE_OBJECT_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:_()&+-]*$")


class TrajectoryReplayCalculationStatus(StrEnum):
    """Complete-only replay lifecycle."""

    COMPLETED = "completed"


class TrajectoryTrackSegmentStartReason(StrEnum):
    """Why one flat-map-safe segment begins."""

    REQUEST_START = "request_start"
    DATELINE_WRAP = "dateline_wrap"


class TrajectoryReplayRequest(BaseModel):
    """Bounded offline replay request over one pinned orbital element set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    orbital_source: PinnedOrbitElementSet
    trajectory_reference: str = Field(default="", max_length=MAX_TRAJECTORY_REFERENCE_LENGTH)
    start_time: datetime
    end_time: datetime
    sample_interval_seconds: int = Field(
        ge=MIN_REPLAY_SAMPLE_INTERVAL_SECONDS,
        le=MAX_REPLAY_SAMPLE_INTERVAL_SECONDS,
    )
    observer: GeodeticPosition | None = None
    maximum_samples: int = Field(default=MAX_REPLAY_SAMPLES, ge=2, le=MAX_REPLAY_SAMPLES)

    @model_validator(mode="after")
    def _validate_request(self) -> TrajectoryReplayRequest:
        start = _normalize_utc(self.start_time, "start_time")
        end = _normalize_utc(self.end_time, "end_time")
        if end <= start:
            raise ValueError("trajectory replay end_time must be after start_time")
        if _duration_microseconds(start, end) > MAX_REPLAY_DURATION_SECONDS * 1_000_000:
            raise ValueError("trajectory replay duration must not exceed 24 hours")
        reference = self.trajectory_reference or (
            f"orbital-elements:{self.orbital_source.element_checksum}"
        )
        if (
            len(reference) > MAX_TRAJECTORY_REFERENCE_LENGTH
            or _OPAQUE_REFERENCE.fullmatch(reference) is None
        ):
            raise ValueError("trajectory_reference must be a bounded opaque reference")
        sample_count = _expected_sample_count(start, end, self.sample_interval_seconds)
        if sample_count > self.maximum_samples:
            raise ValueError("trajectory replay request exceeds the explicit sample bound")
        object.__setattr__(self, "start_time", start)
        object.__setattr__(self, "end_time", end)
        object.__setattr__(self, "trajectory_reference", reference)
        return self

    def expected_sample_count(self) -> int:
        """Return the exact endpoint-inclusive sample count without propagation."""

        return _expected_sample_count(
            ensure_utc(self.start_time),
            ensure_utc(self.end_time),
            self.sample_interval_seconds,
        )

    @property
    def input_reference(self) -> str:
        return f"trajectory-replay-input:{trajectory_replay_request_checksum(self)}"


class TrajectoryReplaySample(BaseModel):
    """One verified geodetic replay sample, optionally relative to a fixed observer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sequence: int = Field(ge=0, le=MAX_REPLAY_SAMPLES - 1)
    timestamp: datetime
    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, lt=180.0)
    altitude_km: float
    observer_azimuth_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    observer_elevation_deg: float | None = Field(default=None, ge=-90.0, le=90.0)
    observer_slant_range_km: float | None = Field(default=None, gt=0.0)
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION

    @model_validator(mode="after")
    def _validate_sample(self) -> TrajectoryReplaySample:
        timestamp = _normalize_utc(self.timestamp, "sample timestamp")
        for value, name in (
            (self.latitude_deg, "latitude_deg"),
            (self.longitude_deg, "longitude_deg"),
            (self.altitude_km, "altitude_km"),
        ):
            _require_finite(value, name)
        observer_values = (
            self.observer_azimuth_deg,
            self.observer_elevation_deg,
            self.observer_slant_range_km,
        )
        if any(value is None for value in observer_values) and any(
            value is not None for value in observer_values
        ):
            raise ValueError("observer-relative values must be present or absent together")
        for observer_value, name in zip(
            observer_values,
            ("observer_azimuth_deg", "observer_elevation_deg", "observer_slant_range_km"),
            strict=True,
        ):
            if observer_value is not None:
                _require_finite(observer_value, name)
        if self.epistemic_status is not EpistemicStatus.DETERMINISTIC_CALCULATION:
            raise ValueError("trajectory replay samples are deterministic calculations")
        object.__setattr__(self, "timestamp", timestamp)
        return self


class TrajectoryTrackSegment(BaseModel):
    """One contiguous sample-index range safe for a flat-map polyline."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    segment_index: int = Field(ge=0, le=MAX_REPLAY_SAMPLES - 1)
    sample_indexes: tuple[int, ...] = Field(min_length=1, max_length=MAX_REPLAY_SAMPLES)
    start_time: datetime
    end_time: datetime
    start_reason: TrajectoryTrackSegmentStartReason

    @model_validator(mode="after")
    def _validate_segment(self) -> TrajectoryTrackSegment:
        start = _normalize_utc(self.start_time, "segment start_time")
        end = _normalize_utc(self.end_time, "segment end_time")
        if end < start:
            raise ValueError("trajectory segment end_time must not precede start_time")
        if self.sample_indexes[0] < 0:
            raise ValueError("trajectory segment sample indexes must be non-negative")
        if any(current != previous + 1 for previous, current in pairwise(self.sample_indexes)):
            raise ValueError("trajectory segment sample indexes must be contiguous")
        expected_reason = (
            TrajectoryTrackSegmentStartReason.REQUEST_START
            if self.segment_index == 0
            else TrajectoryTrackSegmentStartReason.DATELINE_WRAP
        )
        if self.start_reason is not expected_reason:
            raise ValueError("trajectory segment start reason does not match its index")
        object.__setattr__(self, "start_time", start)
        object.__setattr__(self, "end_time", end)
        return self


class TrajectoryReplaySourceIdentity(BaseModel):
    """Safe source and model identity without raw orbital element text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    object_id: str = Field(min_length=1, max_length=160)
    object_label: str = Field(min_length=1, max_length=160)
    norad_catalog_id: int | None
    trajectory_reference: str = Field(min_length=1, max_length=MAX_TRAJECTORY_REFERENCE_LENGTH)
    source_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_epoch: datetime
    propagator_identifier: Literal["orbitmind-sgp4-wgs72-1.0"] = COMPUTATION_VERSION
    frame_model_identifier: Literal["orbitmind-teme-gmst-pef-wgs84-1.0"] = (
        FRAME_GEODETIC_MODEL_VERSION
    )
    observer_geometry_identifier: Literal["orbitmind-look-angle-geometry-1.0"] = (
        OBSERVER_GEOMETRY_MODEL_VERSION
    )

    @model_validator(mode="after")
    def _validate_identity(self) -> TrajectoryReplaySourceIdentity:
        epoch = _normalize_utc(self.source_epoch, "source_epoch")
        if _SAFE_OBJECT_ID.fullmatch(self.object_id) is None:
            raise ValueError("trajectory replay object_id must be a safe opaque identifier")
        if _SAFE_OBJECT_LABEL.fullmatch(self.object_label) is None:
            raise ValueError("trajectory replay object_label must be safe display text")
        if _OPAQUE_REFERENCE.fullmatch(self.trajectory_reference) is None:
            raise ValueError("trajectory replay source reference must be opaque")
        object.__setattr__(self, "source_epoch", epoch)
        return self


class TrajectoryReplayResult(BaseModel):
    """Complete deterministic replay projection; partial results are not representable."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["trajectory-replay-v1"] = TRAJECTORY_REPLAY_SCHEMA_VERSION
    engine_version: Literal["orbitmind-trajectory-replay-1.0"] = TRAJECTORY_REPLAY_ENGINE_VERSION
    source_identity: TrajectoryReplaySourceIdentity
    request_start: datetime
    request_end: datetime
    sample_interval_seconds: int = Field(
        ge=MIN_REPLAY_SAMPLE_INTERVAL_SECONDS,
        le=MAX_REPLAY_SAMPLE_INTERVAL_SECONDS,
    )
    maximum_samples: int = Field(ge=2, le=MAX_REPLAY_SAMPLES)
    observer: GeodeticPosition | None = None
    samples: tuple[TrajectoryReplaySample, ...] = Field(
        min_length=2,
        max_length=MAX_REPLAY_SAMPLES,
    )
    sample_count: int = Field(ge=2, le=MAX_REPLAY_SAMPLES)
    track_segments: tuple[TrajectoryTrackSegment, ...] = Field(
        min_length=1,
        max_length=MAX_REPLAY_SAMPLES,
    )
    source_start_offset_seconds: float
    source_end_offset_seconds: float
    calculation_status: TrajectoryReplayCalculationStatus = (
        TrajectoryReplayCalculationStatus.COMPLETED
    )
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION
    limitations: tuple[str, ...] = TRAJECTORY_REPLAY_LIMITATIONS
    input_reference: str = Field(pattern=r"^trajectory-replay-input:[0-9a-f]{64}$")
    result_reference: str = ""

    @model_validator(mode="after")
    def _validate_result(self) -> TrajectoryReplayResult:
        start = _normalize_utc(self.request_start, "request_start")
        end = _normalize_utc(self.request_end, "request_end")
        if end <= start:
            raise ValueError("trajectory replay result interval is invalid")
        if self.sample_count != len(self.samples):
            raise ValueError("trajectory replay sample_count must match samples")
        if self.sample_count > self.maximum_samples:
            raise ValueError("trajectory replay result exceeds its explicit sample bound")
        _validate_sample_order(self.samples, start, end, self.sample_interval_seconds)
        _validate_observer_projection(self.samples, self.observer)
        _validate_track_segments(self.track_segments, self.samples)
        expected_start_offset = (start - self.source_identity.source_epoch).total_seconds()
        expected_end_offset = (end - self.source_identity.source_epoch).total_seconds()
        if self.source_start_offset_seconds != expected_start_offset:
            raise ValueError("trajectory replay source start offset is inconsistent")
        if self.source_end_offset_seconds != expected_end_offset:
            raise ValueError("trajectory replay source end offset is inconsistent")
        if self.limitations != TRAJECTORY_REPLAY_LIMITATIONS:
            raise ValueError("trajectory replay must retain the fixed limitation set")
        if self.epistemic_status is not EpistemicStatus.DETERMINISTIC_CALCULATION:
            raise ValueError("trajectory replay result is a deterministic calculation")
        object.__setattr__(self, "request_start", start)
        object.__setattr__(self, "request_end", end)
        expected_reference = f"trajectory-replay-result:{trajectory_replay_result_checksum(self)}"
        if self.result_reference and self.result_reference != expected_reference:
            raise ValueError("trajectory replay result reference does not match output")
        object.__setattr__(self, "result_reference", expected_reference)
        return self


def trajectory_replay_request_checksum(request: TrajectoryReplayRequest) -> str:
    """Hash every scientifically relevant normalized replay input without raw TLE text."""

    return sha256_canonical_json(
        {
            "schema_version": TRAJECTORY_REPLAY_SCHEMA_VERSION,
            "engine_version": TRAJECTORY_REPLAY_ENGINE_VERSION,
            "propagator_identifier": COMPUTATION_VERSION,
            "frame_model_identifier": FRAME_GEODETIC_MODEL_VERSION,
            "observer_geometry_identifier": OBSERVER_GEOMETRY_MODEL_VERSION,
            "element_checksum": request.orbital_source.element_checksum,
            "source_checksum": request.orbital_source.source.checksum,
            "source_epoch": _canonical_time(request.orbital_source.orbit_epoch),
            "trajectory_reference": request.trajectory_reference,
            "start_time": _canonical_time(request.start_time),
            "end_time": _canonical_time(request.end_time),
            "sample_interval_seconds": request.sample_interval_seconds,
            "maximum_samples": request.maximum_samples,
            "observer": (
                request.observer.model_dump(mode="json") if request.observer is not None else None
            ),
        }
    )


def trajectory_replay_result_checksum(result: TrajectoryReplayResult) -> str:
    """Hash the complete ordered replay output, excluding its own reference."""

    return sha256_canonical_json(
        result.model_dump(mode="json", exclude={"result_reference"}, round_trip=True)
    )


def _expected_sample_count(start: datetime, end: datetime, step_seconds: int) -> int:
    duration_us = _duration_microseconds(start, end)
    step_us = step_seconds * 1_000_000
    complete_steps, remainder_us = divmod(duration_us, step_us)
    return complete_steps + 1 + int(remainder_us > 0)


def _duration_microseconds(start: datetime, end: datetime) -> int:
    delta = end - start
    return delta.days * 86_400 * 1_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    try:
        return ensure_utc(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware UTC") from exc


def _canonical_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat(timespec="microseconds")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _validate_sample_order(
    samples: tuple[TrajectoryReplaySample, ...],
    start: datetime,
    end: datetime,
    step_seconds: int,
) -> None:
    if samples[0].timestamp != start or samples[-1].timestamp != end:
        raise ValueError("trajectory replay samples must include exact request endpoints")
    for expected_sequence, sample in enumerate(samples):
        if sample.sequence != expected_sequence:
            raise ValueError("trajectory replay sample sequence must be contiguous")
    sample_pairs = tuple(pairwise(samples))
    for pair_index, (previous, current) in enumerate(sample_pairs):
        delta = current.timestamp - previous.timestamp
        expected_step = timedelta(seconds=step_seconds)
        is_final_pair = pair_index == len(sample_pairs) - 1
        if delta <= timedelta(0) or delta > expected_step:
            raise ValueError("trajectory replay sample timestamps are not ordered by step")
        if not is_final_pair and delta != expected_step:
            raise ValueError("trajectory replay intermediate sample cadence is inconsistent")


def _validate_observer_projection(
    samples: tuple[TrajectoryReplaySample, ...],
    observer: GeodeticPosition | None,
) -> None:
    for sample in samples:
        has_observer_values = sample.observer_azimuth_deg is not None
        if (observer is None and has_observer_values) or (
            observer is not None and not has_observer_values
        ):
            raise ValueError("trajectory replay observer values do not match the request")


def _validate_track_segments(
    segments: tuple[TrajectoryTrackSegment, ...],
    samples: tuple[TrajectoryReplaySample, ...],
) -> None:
    if tuple(segment.segment_index for segment in segments) != tuple(range(len(segments))):
        raise ValueError("trajectory replay segment indexes must be contiguous")
    flattened = tuple(index for segment in segments for index in segment.sample_indexes)
    if flattened != tuple(range(len(samples))):
        raise ValueError("trajectory replay segments must contain every sample exactly once")
    for segment in segments:
        first = samples[segment.sample_indexes[0]]
        last = samples[segment.sample_indexes[-1]]
        if segment.start_time != first.timestamp or segment.end_time != last.timestamp:
            raise ValueError("trajectory replay segment times must match their samples")
        for left_index, right_index in pairwise(segment.sample_indexes):
            if _longitude_jump(samples[left_index], samples[right_index]):
                raise ValueError("trajectory replay segment crosses the dateline")
    for previous, current in pairwise(segments):
        left = samples[previous.sample_indexes[-1]]
        right = samples[current.sample_indexes[0]]
        if not _longitude_jump(left, right):
            raise ValueError("trajectory replay contains a false dateline split")


def _longitude_jump(left: TrajectoryReplaySample, right: TrajectoryReplaySample) -> bool:
    return abs(right.longitude_deg - left.longitude_deg) > 180.0
