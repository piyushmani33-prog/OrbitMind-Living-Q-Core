"""Structural verification for bounded observation geometry results."""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from sgp4.api import Satrec

from orbitmind.core.timeutils import ensure_utc
from orbitmind.observation_geometry.models import (
    COARSE_SAMPLING_LIMITATION,
    GEOMETRY_SCHEMA_VERSION,
    ComputedVisibilityInterval,
    GeometryComputationRequest,
    GeometryComputationResult,
    GeometrySample,
    GeometrySampleStatus,
    GeometryVerificationCheck,
    GeometryVerificationResult,
    PinnedOrbitElementSet,
    element_set_checksum,
    geometry_checksum,
    request_checksum,
)
from orbitmind.observation_geometry.service import _sgp4_position_km


def verify_geometry_result(
    result: GeometryComputationResult,
    *,
    request: GeometryComputationRequest | None = None,
) -> GeometryVerificationResult:
    """Verify result structure, checksums, ordered samples, intervals, and limitations."""

    checks: list[GeometryVerificationCheck] = []
    _add(checks, "schema_version", result.schema_version == GEOMETRY_SCHEMA_VERSION)
    try:
        recomputed_geometry = geometry_checksum(result)
    except (TypeError, ValueError):
        recomputed_geometry = None
    _add(
        checks,
        "geometry_checksum",
        recomputed_geometry is not None and result.geometry_checksum == recomputed_geometry,
    )
    if request is not None:
        _add(checks, "request_checksum", result.request_checksum == request_checksum(request))
        _add(
            checks, "element_checksum", result.element_checksum == request.elements.element_checksum
        )
        _add(checks, "sample_horizon", _samples_within_horizon(result.samples, request))
        _add(checks, "sample_step", _samples_match_step(result.samples, request))
        _add(checks, "threshold_consistency", _intervals_match_threshold(result, request))
    _add(checks, "sample_count", result.sample_count == len(result.samples))
    _add(
        checks,
        "failed_sample_count",
        result.failed_sample_count
        == sum(1 for sample in result.samples if sample.status is GeometrySampleStatus.ERROR),
    )
    _add(checks, "sample_order", _strictly_ordered([sample.timestamp for sample in result.samples]))
    _add(checks, "sample_shapes", all(_valid_sample_shape(sample) for sample in result.samples))
    _add(checks, "interval_order", _valid_interval_order(result.intervals))
    _add(checks, "interval_containment", _intervals_contained(result.intervals, result.samples))
    _add(
        checks,
        "interval_failures",
        _intervals_do_not_bridge_failures(result.intervals, result.samples),
    )
    _add(checks, "limitations", COARSE_SAMPLING_LIMITATION in result.limitations)
    return GeometryVerificationResult(
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
        recomputed_checksum=recomputed_geometry,
    )


def verify_sgp4_reference_vector(
    elements: PinnedOrbitElementSet,
    *,
    timestamp: datetime,
    expected_teme_km: tuple[float, float, float],
    tolerance_km: float,
) -> GeometryVerificationResult:
    """Compare one pinned SGP4 TEME vector against a documented reference vector."""

    satrec = Satrec.twoline2rv(elements.tle_line1, elements.tle_line2)
    error_code, actual = _sgp4_position_km(satrec, ensure_utc(timestamp))
    expected_checksum = element_set_checksum(elements)
    checks: list[GeometryVerificationCheck] = []
    _add(checks, "element_checksum", elements.element_checksum == expected_checksum)
    _add(checks, "sgp4_status", error_code == 0 and actual is not None)
    if actual is not None:
        distance = math.sqrt(
            sum((actual[index] - expected_teme_km[index]) ** 2 for index in range(3))
        )
        _add(checks, "reference_vector", distance <= tolerance_km)
    else:
        _add(checks, "reference_vector", False)
    return GeometryVerificationResult(
        passed=all(check.passed for check in checks),
        checks=tuple(checks),
        recomputed_checksum=expected_checksum,
    )


def _add(checks: list[GeometryVerificationCheck], check_id: str, passed: bool) -> None:
    checks.append(
        GeometryVerificationCheck(
            check_id=check_id,
            passed=passed,
            message=f"{check_id} {'passed' if passed else 'failed'}",
        )
    )


def _strictly_ordered(values: list[datetime]) -> bool:
    return all(values[index] < values[index + 1] for index in range(len(values) - 1))


def _valid_sample_shape(sample: GeometrySample) -> bool:
    try:
        if sample.status is GeometrySampleStatus.OK:
            return (
                sample.azimuth_deg is not None
                and 0.0 <= sample.azimuth_deg < 360.0
                and sample.elevation_deg is not None
                and -90.0 <= sample.elevation_deg <= 90.0
                and sample.slant_range_km is not None
                and sample.slant_range_km > 0.0
                and math.isfinite(sample.azimuth_deg)
                and math.isfinite(sample.elevation_deg)
                and math.isfinite(sample.slant_range_km)
                and sample.safe_error_code is None
            )
        return (
            sample.azimuth_deg is None
            and sample.elevation_deg is None
            and sample.slant_range_km is None
            and sample.safe_error_code is not None
        )
    except TypeError:
        return False


def _samples_within_horizon(
    samples: tuple[GeometrySample, ...],
    request: GeometryComputationRequest,
) -> bool:
    return all(request.start <= sample.timestamp <= request.end for sample in samples)


def _samples_match_step(
    samples: tuple[GeometrySample, ...],
    request: GeometryComputationRequest,
) -> bool:
    if len(samples) != request.expected_sample_count():
        return False
    for index, sample in enumerate(samples):
        expected = request.start + timedelta(seconds=index * request.step_seconds)
        if sample.timestamp != expected:
            return False
    return True


def _valid_interval_order(intervals: tuple[ComputedVisibilityInterval, ...]) -> bool:
    for index, interval in enumerate(intervals):
        if not (interval.rise_time <= interval.peak_time <= interval.set_time):
            return False
        if index and intervals[index - 1].set_time > interval.rise_time:
            return False
    return True


def _intervals_contained(
    intervals: tuple[ComputedVisibilityInterval, ...],
    samples: tuple[GeometrySample, ...],
) -> bool:
    if not samples:
        return not intervals
    first = samples[0].timestamp
    last = samples[-1].timestamp
    return all(first <= interval.rise_time <= interval.set_time <= last for interval in intervals)


def _intervals_do_not_bridge_failures(
    intervals: tuple[ComputedVisibilityInterval, ...],
    samples: tuple[GeometrySample, ...],
) -> bool:
    failed_times = [
        sample.timestamp for sample in samples if sample.status is GeometrySampleStatus.ERROR
    ]
    return all(
        not (interval.rise_time <= failed_time <= interval.set_time)
        for interval in intervals
        for failed_time in failed_times
    )


def _intervals_match_threshold(
    result: GeometryComputationResult,
    request: GeometryComputationRequest,
) -> bool:
    successful = [sample for sample in result.samples if sample.status is GeometrySampleStatus.OK]
    for interval in result.intervals:
        inside = [
            sample
            for sample in successful
            if interval.rise_time <= sample.timestamp <= interval.set_time
        ]
        if not inside or max(sample.elevation_deg or -91.0 for sample in inside) < (
            request.minimum_elevation_deg
        ):
            return False
    return True
