"""Bounded deterministic look-angle and sampled visibility computation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast

from sgp4.api import Satrec, jday

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.observation_geometry.geodesy import look_angles_from_ecef, teme_to_ecef_km
from orbitmind.observation_geometry.models import (
    GEOMETRY_COMPUTATION_VERSION,
    MAX_REFINEMENT_ITERATIONS_PER_CROSSING,
    MAX_TOTAL_REFINEMENT_EVALUATIONS,
    MAX_VISIBILITY_INTERVALS,
    REFINEMENT_TIME_TOLERANCE_SECONDS,
    ComputedVisibilityInterval,
    GeometryComputationRequest,
    GeometryComputationResult,
    GeometrySample,
    GeometrySampleStatus,
    VisibilityRefinementStatus,
    source_identity_checksum,
)


@dataclass
class _PropagationOutcome:
    sample: GeometrySample
    ecef_km: tuple[float, float, float] | None = None


@dataclass
class _Boundary:
    sample: GeometrySample
    clipped: bool
    status: VisibilityRefinementStatus


def compute_observation_geometry(
    request: GeometryComputationRequest,
) -> GeometryComputationResult:
    """Compute bounded look-angle samples and sampled visibility intervals."""

    satrec = Satrec.twoline2rv(request.elements.tle_line1, request.elements.tle_line2)
    samples = tuple(
        _propagate_look_angle(satrec, request, timestamp).sample
        for timestamp in _primary_sample_times(request)
    )
    intervals = _visibility_intervals(satrec, request, samples)
    return GeometryComputationResult(
        request_checksum=request.request_checksum,
        element_checksum=request.elements.element_checksum,
        source_identity_checksum=source_identity_checksum(request.elements.source),
        samples=samples,
        intervals=intervals,
        sample_count=len(samples),
        failed_sample_count=sum(
            1 for sample in samples if sample.status is GeometrySampleStatus.ERROR
        ),
        computation_version=GEOMETRY_COMPUTATION_VERSION,
    )


def _primary_sample_times(request: GeometryComputationRequest) -> tuple[datetime, ...]:
    start = ensure_utc(request.start)
    return tuple(
        start + timedelta(seconds=index * request.step_seconds)
        for index in range(request.expected_sample_count())
    )


def _propagate_look_angle(
    satrec: Satrec,
    request: GeometryComputationRequest,
    timestamp: datetime,
) -> _PropagationOutcome:
    timestamp = ensure_utc(timestamp)
    error_code, teme_km = _sgp4_position_km(satrec, timestamp)
    if error_code != 0 or teme_km is None:
        return _PropagationOutcome(
            GeometrySample(
                timestamp=timestamp,
                status=GeometrySampleStatus.ERROR,
                safe_error_code=f"sgp4_status_{error_code}",
            )
        )
    seconds = timestamp.second + timestamp.microsecond / 1_000_000.0
    jd, fr = jday(
        timestamp.year,
        timestamp.month,
        timestamp.day,
        timestamp.hour,
        timestamp.minute,
        seconds,
    )
    ecef = teme_to_ecef_km(teme_km, float(jd + fr))
    azimuth, elevation, slant_range = look_angles_from_ecef(ecef, request.site.position)
    return _PropagationOutcome(
        GeometrySample(
            timestamp=timestamp,
            status=GeometrySampleStatus.OK,
            azimuth_deg=azimuth,
            elevation_deg=elevation,
            slant_range_km=slant_range,
        ),
        ecef_km=ecef,
    )


def _sgp4_position_km(
    satrec: Satrec,
    timestamp: datetime,
) -> tuple[int, tuple[float, float, float] | None]:
    timestamp = ensure_utc(timestamp)
    seconds = timestamp.second + timestamp.microsecond / 1_000_000.0
    jd, fr = jday(
        timestamp.year,
        timestamp.month,
        timestamp.day,
        timestamp.hour,
        timestamp.minute,
        seconds,
    )
    error_code, position, _velocity = satrec.sgp4(jd, fr)
    if error_code != 0:
        return (int(error_code), None)
    return (0, cast(tuple[float, float, float], tuple(float(component) for component in position)))


def _visibility_intervals(
    satrec: Satrec,
    request: GeometryComputationRequest,
    samples: tuple[GeometrySample, ...],
) -> tuple[ComputedVisibilityInterval, ...]:
    intervals: list[ComputedVisibilityInterval] = []
    refinement_evaluations = 0
    run_start: int | None = None
    for index, sample in enumerate(samples):
        visible = _sample_visible(sample, request.minimum_elevation_deg)
        if visible and run_start is None:
            run_start = index
        next_break = (
            index == len(samples) - 1
            or samples[index + 1].status is GeometrySampleStatus.ERROR
            or not _sample_visible(samples[index + 1], request.minimum_elevation_deg)
        )
        if run_start is not None and visible and next_break:
            interval, used = _build_interval(
                satrec,
                request,
                samples,
                run_start,
                index,
                refinement_evaluations,
            )
            refinement_evaluations += used
            intervals.append(interval)
            if len(intervals) > MAX_VISIBILITY_INTERVALS:
                raise ValidationError("visibility interval count exceeds bounded limit")
            run_start = None
        if sample.status is GeometrySampleStatus.ERROR:
            run_start = None
    return tuple(intervals)


def _build_interval(
    satrec: Satrec,
    request: GeometryComputationRequest,
    samples: tuple[GeometrySample, ...],
    start_index: int,
    end_index: int,
    evaluations_so_far: int,
) -> tuple[ComputedVisibilityInterval, int]:
    used = 0
    first = samples[start_index]
    last = samples[end_index]
    previous = samples[start_index - 1] if start_index > 0 else None
    following = samples[end_index + 1] if end_index + 1 < len(samples) else None

    rise = _Boundary(first, clipped=start_index == 0, status=VisibilityRefinementStatus.CLIPPED)
    if previous is not None and previous.status is GeometrySampleStatus.OK:
        refined, used_now = _refine_crossing(
            satrec,
            request,
            previous,
            first,
            rising=True,
            evaluations_so_far=evaluations_so_far + used,
        )
        rise = refined
        used += used_now
    elif start_index != 0:
        rise = _Boundary(first, clipped=True, status=VisibilityRefinementStatus.CLIPPED)

    set_boundary = _Boundary(
        last,
        clipped=end_index == len(samples) - 1,
        status=VisibilityRefinementStatus.CLIPPED,
    )
    if following is not None and following.status is GeometrySampleStatus.OK:
        refined, used_now = _refine_crossing(
            satrec,
            request,
            last,
            following,
            rising=False,
            evaluations_so_far=evaluations_so_far + used,
        )
        set_boundary = refined
        used += used_now
    elif end_index != len(samples) - 1:
        set_boundary = _Boundary(last, clipped=True, status=VisibilityRefinementStatus.CLIPPED)

    successful_run = [
        sample
        for sample in samples[start_index : end_index + 1]
        if sample.status is GeometrySampleStatus.OK
    ]
    peak = max(successful_run, key=lambda sample: sample.elevation_deg or -91.0)
    status = _combined_refinement_status(rise.status, set_boundary.status)
    return (
        ComputedVisibilityInterval(
            rise_time=rise.sample.timestamp,
            set_time=set_boundary.sample.timestamp,
            peak_time=peak.timestamp,
            peak_elevation_deg=peak.elevation_deg or -90.0,
            rise_azimuth_deg=rise.sample.azimuth_deg or first.azimuth_deg or 0.0,
            set_azimuth_deg=set_boundary.sample.azimuth_deg or last.azimuth_deg or 0.0,
            rise_boundary_clipped=rise.clipped,
            set_boundary_clipped=set_boundary.clipped,
            refinement_status=status,
        ),
        used,
    )


def _refine_crossing(
    satrec: Satrec,
    request: GeometryComputationRequest,
    left: GeometrySample,
    right: GeometrySample,
    *,
    rising: bool,
    evaluations_so_far: int,
) -> tuple[_Boundary, int]:
    low_time = left.timestamp
    high_time = right.timestamp
    low_visible = _sample_visible(left, request.minimum_elevation_deg)
    high_visible = _sample_visible(right, request.minimum_elevation_deg)
    visible_sample = right if rising else left
    if low_visible == high_visible:
        return (
            _Boundary(visible_sample, clipped=False, status=VisibilityRefinementStatus.SAMPLED),
            0,
        )
    used = 0
    best = visible_sample
    status = VisibilityRefinementStatus.REFINED
    for _ in range(MAX_REFINEMENT_ITERATIONS_PER_CROSSING):
        if evaluations_so_far + used >= MAX_TOTAL_REFINEMENT_EVALUATIONS:
            raise ValidationError("visibility refinement evaluation bound exceeded")
        if (high_time - low_time).total_seconds() <= REFINEMENT_TIME_TOLERANCE_SECONDS:
            break
        mid_time = low_time + (high_time - low_time) / 2
        mid = _propagate_look_angle(satrec, request, mid_time).sample
        used += 1
        if mid.status is GeometrySampleStatus.ERROR:
            status = VisibilityRefinementStatus.REFINEMENT_FAILED
            break
        mid_visible = _sample_visible(mid, request.minimum_elevation_deg)
        if mid_visible:
            best = mid
        if mid_visible == low_visible:
            low_time = mid_time
            low_visible = mid_visible
        else:
            high_time = mid_time
            high_visible = mid_visible
    return (_Boundary(best, clipped=False, status=status), used)


def _sample_visible(sample: GeometrySample, threshold_deg: float) -> bool:
    return (
        sample.status is GeometrySampleStatus.OK
        and sample.elevation_deg is not None
        and sample.elevation_deg >= threshold_deg
    )


def _combined_refinement_status(
    rise: VisibilityRefinementStatus,
    set_boundary: VisibilityRefinementStatus,
) -> VisibilityRefinementStatus:
    statuses = {rise, set_boundary}
    if VisibilityRefinementStatus.REFINEMENT_FAILED in statuses:
        return VisibilityRefinementStatus.REFINEMENT_FAILED
    if VisibilityRefinementStatus.REFINED in statuses:
        return VisibilityRefinementStatus.REFINED
    if statuses == {VisibilityRefinementStatus.CLIPPED}:
        return VisibilityRefinementStatus.CLIPPED
    return VisibilityRefinementStatus.SAMPLED
