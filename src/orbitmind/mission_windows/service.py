"""Bounded deterministic event search for offline Earth-observer mission windows."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.mission_windows.models import (
    EVENT_TIME_TOLERANCE_SECONDS,
    MAX_CROSSING_REFINEMENT_ITERATIONS,
    MAX_MISSION_WINDOWS,
    MAX_PEAK_REFINEMENT_ITERATIONS,
    MAX_TOTAL_GEOMETRY_EVALUATIONS,
    PEAK_TIME_TOLERANCE_SECONDS,
    MissionWindowEvent,
    MissionWindowRequest,
    MissionWindowResult,
    MissionWindowSourceIdentity,
    classify_mission_window_event,
)
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometrySample,
    GeometrySampleStatus,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.service import ObservationGeometryEvaluator


class LookAngleEvaluator(Protocol):
    """Injected deterministic single-time observer-geometry evaluator."""

    def evaluate(self, timestamp: datetime) -> GeometrySample: ...


class LookAngleEvaluatorFactory(Protocol):
    """Construct one evaluator for a pinned element set and fixed site."""

    def __call__(
        self,
        *,
        elements: PinnedOrbitElementSet,
        site: GroundObservationSite,
    ) -> LookAngleEvaluator: ...


@dataclass
class _EvaluationBudget:
    evaluator: LookAngleEvaluator
    used: int = 0

    def evaluate(self, timestamp: datetime) -> GeometrySample:
        if self.used >= MAX_TOTAL_GEOMETRY_EVALUATIONS:
            raise ValidationError("mission-window geometry evaluation bound exceeded")
        self.used += 1
        expected_timestamp = ensure_utc(timestamp)
        try:
            sample = self.evaluator.evaluate(expected_timestamp)
        except (ArithmeticError, RuntimeError, ValueError) as exc:
            raise ValidationError("mission-window geometry evaluation failed") from exc
        if sample.timestamp != expected_timestamp:
            raise ValidationError("mission-window geometry evaluation timestamp mismatch")
        if sample.status is not GeometrySampleStatus.OK:
            raise ValidationError("mission-window geometry evaluation failed")
        if (
            sample.azimuth_deg is None
            or sample.elevation_deg is None
            or sample.slant_range_km is None
        ):
            raise ValidationError("mission-window geometry evaluation was incomplete")
        return sample


class MissionWindowService:
    """Calculate refined geometric windows from one pinned offline orbital source."""

    def __init__(
        self,
        evaluator_factory: LookAngleEvaluatorFactory = ObservationGeometryEvaluator,
    ) -> None:
        self._evaluator_factory = evaluator_factory

    def calculate(self, request: MissionWindowRequest) -> MissionWindowResult:
        """Return ordered windows or an empty successful result for a valid request."""

        site = GroundObservationSite(
            site_id="mission-window-observer",
            name=request.observer.label,
            position=GeodeticPosition(
                latitude_deg=request.observer.latitude_deg,
                longitude_deg=request.observer.longitude_deg,
                altitude_km=request.observer.altitude_metres / 1_000.0,
            ),
        )
        try:
            evaluator = self._evaluator_factory(
                elements=request.orbital_source,
                site=site,
            )
        except (RuntimeError, ValueError) as exc:
            raise ValidationError("mission-window geometry evaluator could not initialize") from exc
        budget = _EvaluationBudget(evaluator)
        samples = tuple(budget.evaluate(timestamp) for timestamp in _coarse_times(request))
        windows = _find_windows(request, samples, budget)
        source = request.orbital_source.source
        source_epoch = request.orbital_source.orbit_epoch
        start_offset = (
            (request.start_time - source_epoch).total_seconds()
            if source_epoch is not None
            else None
        )
        end_offset = (
            (request.end_time - source_epoch).total_seconds() if source_epoch is not None else None
        )
        return MissionWindowResult(
            source_identity=MissionWindowSourceIdentity(
                object_id=source.satellite_id,
                object_name=source.name,
                norad_catalog_id=source.norad_cat_id,
                source_name=source.source_name,
                source_checksum=source.checksum,
                test_only=source.test_only,
            ),
            trajectory_reference=request.trajectory_reference,
            source_epoch=source_epoch,
            request_start=request.start_time,
            request_end=request.end_time,
            observer=request.observer,
            minimum_elevation_deg=request.minimum_elevation_deg,
            coarse_step_seconds=request.coarse_step_seconds,
            prediction_start_offset_seconds=start_offset,
            prediction_end_offset_seconds=end_offset,
            windows=windows,
            window_count=len(windows),
            input_reference=request.input_reference,
        )


def _coarse_times(request: MissionWindowRequest) -> tuple[datetime, ...]:
    start = ensure_utc(request.start_time)
    end = ensure_utc(request.end_time)
    step = timedelta(seconds=request.coarse_step_seconds)
    times = [start]
    timestamp = start + step
    while timestamp < end:
        times.append(timestamp)
        timestamp += step
    if times[-1] != end:
        times.append(end)
    return tuple(times)


def _find_windows(
    request: MissionWindowRequest,
    samples: tuple[GeometrySample, ...],
    budget: _EvaluationBudget,
) -> tuple[MissionWindowEvent, ...]:
    threshold = request.minimum_elevation_deg
    windows: list[MissionWindowEvent] = []
    first = samples[0]
    active_start: GeometrySample | None = first if _visible(first, threshold) else None
    active_samples: list[GeometrySample] = [first] if active_start is not None else []
    begins_before = (
        active_start is not None and _elevation(active_start) > request.minimum_elevation_deg
    )

    previous = first
    for current in samples[1:]:
        previous_visible = _visible(previous, threshold)
        current_visible = _visible(current, threshold)
        if not previous_visible and current_visible:
            active_start = _refine_crossing(previous, current, threshold, budget)
            active_samples = _append_unique([], active_start)
            active_samples = _append_unique(active_samples, current)
            begins_before = False
        elif previous_visible and current_visible:
            active_samples = _append_unique(active_samples, current)
        elif previous_visible and not current_visible and active_start is not None:
            set_boundary = _refine_crossing(previous, current, threshold, budget)
            active_samples = _append_unique(active_samples, set_boundary)
            event = _build_event(
                active_start,
                set_boundary,
                active_samples,
                begins_before=begins_before,
                ends_after=False,
                budget=budget,
            )
            if event is not None:
                windows.append(event)
                if len(windows) > MAX_MISSION_WINDOWS:
                    raise ValidationError("mission-window event count exceeds bounded limit")
            active_start = None
            active_samples = []
            begins_before = False
        previous = current

    if active_start is not None:
        end_boundary = samples[-1]
        event = _build_event(
            active_start,
            end_boundary,
            active_samples,
            begins_before=begins_before,
            ends_after=_elevation(end_boundary) > threshold,
            budget=budget,
        )
        if event is not None:
            windows.append(event)
    if len(windows) > MAX_MISSION_WINDOWS:
        raise ValidationError("mission-window event count exceeds bounded limit")
    return tuple(windows)


def _refine_crossing(
    left: GeometrySample,
    right: GeometrySample,
    threshold: float,
    budget: _EvaluationBudget,
) -> GeometrySample:
    left_delta = _elevation(left) - threshold
    right_delta = _elevation(right) - threshold
    if left_delta == 0.0:
        return left
    if right_delta == 0.0:
        return right
    if (left_delta > 0.0) == (right_delta > 0.0):
        raise ValidationError("mission-window crossing was not bracketed")

    low = left
    high = right
    low_delta = left_delta
    for _ in range(MAX_CROSSING_REFINEMENT_ITERATIONS):
        if (high.timestamp - low.timestamp).total_seconds() <= EVENT_TIME_TOLERANCE_SECONDS:
            break
        midpoint = budget.evaluate(low.timestamp + (high.timestamp - low.timestamp) / 2)
        midpoint_delta = _elevation(midpoint) - threshold
        if midpoint_delta == 0.0:
            return midpoint
        if (midpoint_delta > 0.0) == (low_delta > 0.0):
            low = midpoint
            low_delta = midpoint_delta
        else:
            high = midpoint
    return budget.evaluate(low.timestamp + (high.timestamp - low.timestamp) / 2)


def _build_event(
    rise: GeometrySample,
    set_boundary: GeometrySample,
    samples: Sequence[GeometrySample],
    *,
    begins_before: bool,
    ends_after: bool,
    budget: _EvaluationBudget,
) -> MissionWindowEvent | None:
    duration_seconds = (set_boundary.timestamp - rise.timestamp).total_seconds()
    if duration_seconds <= EVENT_TIME_TOLERANCE_SECONDS:
        return None
    peak = _refine_peak(samples, rise, set_boundary, budget)
    return MissionWindowEvent(
        rise_time=rise.timestamp,
        peak_time=peak.timestamp,
        set_time=set_boundary.timestamp,
        rise_azimuth_deg=_azimuth(rise),
        peak_azimuth_deg=_azimuth(peak),
        set_azimuth_deg=_azimuth(set_boundary),
        maximum_elevation_deg=_elevation(peak),
        duration_seconds=duration_seconds,
        classification=classify_mission_window_event(begins_before, ends_after),
        begins_before_requested_interval=begins_before,
        ends_after_requested_interval=ends_after,
    )


def _refine_peak(
    samples: Sequence[GeometrySample],
    rise: GeometrySample,
    set_boundary: GeometrySample,
    budget: _EvaluationBudget,
) -> GeometrySample:
    ordered = sorted(
        {sample.timestamp: sample for sample in (*samples, rise, set_boundary)}.values(),
        key=lambda sample: sample.timestamp,
    )
    best = _earliest_maximum(ordered)
    best_index = ordered.index(best)
    low_time = ordered[max(0, best_index - 1)].timestamp
    high_time = ordered[min(len(ordered) - 1, best_index + 1)].timestamp
    if high_time <= low_time:
        return best

    for _ in range(MAX_PEAK_REFINEMENT_ITERATIONS):
        span = high_time - low_time
        if span.total_seconds() <= PEAK_TIME_TOLERANCE_SECONDS:
            break
        left_time = low_time + span / 3
        right_time = high_time - span / 3
        left = budget.evaluate(left_time)
        right = budget.evaluate(right_time)
        best = _earlier_higher(best, left)
        best = _earlier_higher(best, right)
        if _elevation(left) < _elevation(right):
            low_time = left_time
        else:
            high_time = right_time
    midpoint = budget.evaluate(low_time + (high_time - low_time) / 2)
    return _earlier_higher(best, midpoint)


def _earliest_maximum(samples: Sequence[GeometrySample]) -> GeometrySample:
    if not samples:
        raise ValidationError("mission-window peak search has no samples")
    best = samples[0]
    for sample in samples[1:]:
        best = _earlier_higher(best, sample)
    return best


def _earlier_higher(first: GeometrySample, second: GeometrySample) -> GeometrySample:
    first_elevation = _elevation(first)
    second_elevation = _elevation(second)
    if second_elevation > first_elevation:
        return second
    if second_elevation == first_elevation and second.timestamp < first.timestamp:
        return second
    return first


def _append_unique(
    samples: list[GeometrySample],
    sample: GeometrySample,
) -> list[GeometrySample]:
    if not samples or samples[-1].timestamp != sample.timestamp:
        samples.append(sample)
    return samples


def _visible(sample: GeometrySample, threshold: float) -> bool:
    return _elevation(sample) >= threshold


def _azimuth(sample: GeometrySample) -> float:
    if sample.azimuth_deg is None:
        raise ValidationError("mission-window sample has no azimuth")
    return sample.azimuth_deg


def _elevation(sample: GeometrySample) -> float:
    if sample.elevation_deg is None:
        raise ValidationError("mission-window sample has no elevation")
    return sample.elevation_deg
