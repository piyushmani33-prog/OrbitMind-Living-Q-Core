"""Bounded deterministic projection of pinned orbital elements into replay samples."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Protocol

from sgp4.api import Satrec

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.observation_geometry.geodesy import look_angles_from_ecef, teme_to_ecef_km
from orbitmind.observation_geometry.models import GeodeticPosition, PinnedOrbitElementSet
from orbitmind.space.geodesy import ecef_to_geodetic
from orbitmind.space.propagation import propagate_sgp4_state
from orbitmind.trajectory_replay.models import (
    TrajectoryReplayRequest,
    TrajectoryReplayResult,
    TrajectoryReplaySample,
    TrajectoryReplaySourceIdentity,
    TrajectoryTrackSegment,
    TrajectoryTrackSegmentStartReason,
)


@dataclass(frozen=True)
class TrajectoryProjection:
    """Internal scientific projection returned by an injected evaluator."""

    latitude_deg: float
    longitude_deg: float
    altitude_km: float
    observer_azimuth_deg: float | None = None
    observer_elevation_deg: float | None = None
    observer_slant_range_km: float | None = None


class TrajectoryProjectionEvaluator(Protocol):
    """Evaluate one requested UTC instant without sampling or I/O."""

    def evaluate(self, timestamp: datetime) -> TrajectoryProjection: ...


class TrajectoryProjectionEvaluatorFactory(Protocol):
    """Build one evaluator for pinned elements and an optional fixed observer."""

    def __call__(
        self,
        *,
        elements: PinnedOrbitElementSet,
        observer: GeodeticPosition | None,
    ) -> TrajectoryProjectionEvaluator: ...


class _ReviewedTrajectoryProjectionEvaluator:
    """Reuse the reviewed SGP4, Earth-fixed, WGS84, and look-angle primitives."""

    def __init__(
        self,
        *,
        elements: PinnedOrbitElementSet,
        observer: GeodeticPosition | None,
    ) -> None:
        self._satrec = Satrec.twoline2rv(elements.tle_line1, elements.tle_line2)
        self._observer = observer

    def evaluate(self, timestamp: datetime) -> TrajectoryProjection:
        state = propagate_sgp4_state(self._satrec, ensure_utc(timestamp))
        if state.error_code != 0 or state.position_km is None:
            raise ValidationError("trajectory replay SGP4 propagation failed")
        earth_fixed_km = teme_to_ecef_km(
            state.position_km,
            state.julian_date_utc_as_ut1,
        )
        latitude, longitude, altitude = ecef_to_geodetic(*earth_fixed_km)
        if self._observer is None:
            return TrajectoryProjection(
                latitude_deg=latitude,
                longitude_deg=longitude,
                altitude_km=altitude,
            )
        azimuth, elevation, slant_range = look_angles_from_ecef(
            earth_fixed_km,
            self._observer,
        )
        return TrajectoryProjection(
            latitude_deg=latitude,
            longitude_deg=longitude,
            altitude_km=altitude,
            observer_azimuth_deg=azimuth,
            observer_elevation_deg=elevation,
            observer_slant_range_km=slant_range,
        )


class TrajectoryReplayService:
    """Create a complete deterministic replay projection or fail without partial output."""

    def __init__(
        self,
        evaluator_factory: TrajectoryProjectionEvaluatorFactory = (
            _ReviewedTrajectoryProjectionEvaluator
        ),
    ) -> None:
        self._evaluator_factory = evaluator_factory

    def calculate(self, request: TrajectoryReplayRequest) -> TrajectoryReplayResult:
        """Calculate ordered endpoint-inclusive replay samples entirely in memory."""

        source_epoch = request.orbital_source.orbit_epoch
        if source_epoch is None:  # pragma: no cover - pinned elements always validate an epoch.
            raise ValidationError("trajectory replay source epoch is unavailable")
        timestamps = _sample_times(request)
        try:
            evaluator = self._evaluator_factory(
                elements=request.orbital_source,
                observer=request.observer,
            )
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            raise ValidationError("trajectory replay evaluator could not initialize") from exc

        samples: list[TrajectoryReplaySample] = []
        for sequence, timestamp in enumerate(timestamps):
            try:
                projection = evaluator.evaluate(timestamp)
                sample = TrajectoryReplaySample(
                    sequence=sequence,
                    timestamp=timestamp,
                    latitude_deg=projection.latitude_deg,
                    longitude_deg=projection.longitude_deg,
                    altitude_km=projection.altitude_km,
                    observer_azimuth_deg=projection.observer_azimuth_deg,
                    observer_elevation_deg=projection.observer_elevation_deg,
                    observer_slant_range_km=projection.observer_slant_range_km,
                )
            except ValidationError as exc:
                raise ValidationError("trajectory replay sample calculation failed") from exc
            except (ArithmeticError, RuntimeError, ValueError) as exc:
                raise ValidationError("trajectory replay sample calculation failed") from exc
            samples.append(sample)

        ordered_samples = tuple(samples)
        source = request.orbital_source.source
        return TrajectoryReplayResult(
            source_identity=TrajectoryReplaySourceIdentity(
                object_id=source.satellite_id,
                object_label=source.name,
                norad_catalog_id=source.norad_cat_id,
                trajectory_reference=request.trajectory_reference,
                source_checksum=source.checksum,
                source_epoch=source_epoch,
            ),
            request_start=request.start_time,
            request_end=request.end_time,
            sample_interval_seconds=request.sample_interval_seconds,
            maximum_samples=request.maximum_samples,
            observer=request.observer,
            samples=ordered_samples,
            sample_count=len(ordered_samples),
            track_segments=segment_ground_track(ordered_samples),
            source_start_offset_seconds=(request.start_time - source_epoch).total_seconds(),
            source_end_offset_seconds=(request.end_time - source_epoch).total_seconds(),
            input_reference=request.input_reference,
        )


def segment_ground_track(
    samples: Sequence[TrajectoryReplaySample],
) -> tuple[TrajectoryTrackSegment, ...]:
    """Split canonical longitudes at wraps without losing or duplicating samples."""

    if not samples:
        raise ValueError("trajectory replay segmentation requires at least one sample")
    for expected_sequence, sample in enumerate(samples):
        if sample.sequence != expected_sequence:
            raise ValueError("trajectory replay segmentation requires contiguous sample sequence")
        if expected_sequence and sample.timestamp <= samples[expected_sequence - 1].timestamp:
            raise ValueError("trajectory replay segmentation requires ordered timestamps")

    segment_starts = [0]
    for index in range(1, len(samples)):
        previous = samples[index - 1]
        current = samples[index]
        if abs(current.longitude_deg - previous.longitude_deg) > 180.0:
            segment_starts.append(index)
    segment_starts.append(len(samples))

    segments: list[TrajectoryTrackSegment] = []
    for segment_index, (start, stop) in enumerate(pairwise(segment_starts)):
        indexes = tuple(range(start, stop))
        segments.append(
            TrajectoryTrackSegment(
                segment_index=segment_index,
                sample_indexes=indexes,
                start_time=samples[indexes[0]].timestamp,
                end_time=samples[indexes[-1]].timestamp,
                start_reason=(
                    TrajectoryTrackSegmentStartReason.REQUEST_START
                    if segment_index == 0
                    else TrajectoryTrackSegmentStartReason.DATELINE_WRAP
                ),
            )
        )
    return tuple(segments)


def _sample_times(request: TrajectoryReplayRequest) -> tuple[datetime, ...]:
    start = ensure_utc(request.start_time)
    regular_samples = tuple(
        start + timedelta(seconds=index * request.sample_interval_seconds)
        for index in range(request.expected_sample_count() - 1)
    )
    return (*regular_samples, ensure_utc(request.end_time))
