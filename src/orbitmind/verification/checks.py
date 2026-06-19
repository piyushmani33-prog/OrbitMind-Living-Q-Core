"""Deterministic verification checks producing structured findings.

Checks are pure functions of the propagation result + request. They never mutate
the result and never raise on bad data — they record a failed finding instead
(SR-08).
"""

from __future__ import annotations

import math

from orbitmind.core.units import ALTITUDE_MAX_KM, ALTITUDE_MIN_KM, UNITS
from orbitmind.mission.models import MissionRequest
from orbitmind.space.models import SampleStatus, ScientificResult
from orbitmind.verification.models import FindingStatus, Severity, VerificationFinding


class VerificationService:
    """Runs all deterministic checks over a scientific result."""

    def verify(
        self, result: ScientificResult, request: MissionRequest
    ) -> list[VerificationFinding]:
        return [
            self._check_timestamps_utc(result),
            self._check_monotonic_times(result),
            self._check_sample_count(result, request),
            self._check_finite_values(result),
            self._check_coordinate_bounds(result),
            self._check_altitude_bounds(result),
            self._check_propagation_errors(result),
            self._check_unit_consistency(result),
            self._check_provenance_completeness(result),
        ]

    @staticmethod
    def _check_timestamps_utc(result: ScientificResult) -> VerificationFinding:
        bad = [
            i
            for i, s in enumerate(result.samples)
            if s.timestamp.tzinfo is None or s.timestamp.utcoffset() is None
        ]
        passed = not bad
        return VerificationFinding(
            check_id="timestamps_utc",
            severity=Severity.CRITICAL,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                "all timestamps are timezone-aware"
                if passed
                else "found naive (non-UTC) timestamps"
            ),
            values={"naive_indices": bad},
        )

    @staticmethod
    def _check_monotonic_times(result: ScientificResult) -> VerificationFinding:
        times = [s.timestamp for s in result.samples]
        try:
            monotonic = all(times[i] < times[i + 1] for i in range(len(times) - 1))
        except TypeError:
            # Mixed naive/aware timestamps are not comparable; treat as non-monotonic
            # rather than letting the check raise (SR-08).
            monotonic = False
        return VerificationFinding(
            check_id="monotonic_times",
            severity=Severity.ERROR,
            status=FindingStatus.PASSED if monotonic else FindingStatus.FAILED,
            explanation=(
                "sample times strictly increase"
                if monotonic
                else "sample times are not strictly increasing"
            ),
            values={"count": len(times)},
        )

    @staticmethod
    def _check_sample_count(
        result: ScientificResult, request: MissionRequest
    ) -> VerificationFinding:
        expected = request.expected_sample_count()
        actual = len(result.samples)
        passed = expected == actual
        return VerificationFinding(
            check_id="sample_count",
            severity=Severity.ERROR,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                "produced the expected number of samples"
                if passed
                else "sample count differs from expected"
            ),
            values={"expected": expected, "actual": actual},
        )

    @staticmethod
    def _check_finite_values(result: ScientificResult) -> VerificationFinding:
        bad: list[int] = []
        for i, s in enumerate(result.samples):
            if s.status is not SampleStatus.OK:
                continue
            numbers = [s.latitude_deg, s.longitude_deg, s.altitude_km]
            if s.position_km is not None:
                numbers += [s.position_km.x, s.position_km.y, s.position_km.z]
            if any(n is None or not math.isfinite(n) for n in numbers):
                bad.append(i)
        passed = not bad
        return VerificationFinding(
            check_id="finite_values",
            severity=Severity.CRITICAL,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                "all numeric outputs are finite" if passed else "found non-finite numeric outputs"
            ),
            values={"nonfinite_indices": bad},
        )

    @staticmethod
    def _check_coordinate_bounds(result: ScientificResult) -> VerificationFinding:
        bad: list[int] = []
        for i, s in enumerate(result.samples):
            if s.status is not SampleStatus.OK:
                continue
            lat_ok = s.latitude_deg is not None and -90.0 <= s.latitude_deg <= 90.0
            lon_ok = s.longitude_deg is not None and -180.0 <= s.longitude_deg <= 180.0
            if not (lat_ok and lon_ok):
                bad.append(i)
        passed = not bad
        return VerificationFinding(
            check_id="coordinate_bounds",
            severity=Severity.ERROR,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                "latitude/longitude within valid ranges"
                if passed
                else "latitude/longitude out of range"
            ),
            values={"out_of_range_indices": bad},
        )

    @staticmethod
    def _check_altitude_bounds(result: ScientificResult) -> VerificationFinding:
        ok = [s for s in result.samples if s.status is SampleStatus.OK]
        bad = [
            i
            for i, s in enumerate(ok)
            if s.altitude_km is None or not ALTITUDE_MIN_KM <= s.altitude_km <= ALTITUDE_MAX_KM
        ]
        passed = not bad
        return VerificationFinding(
            check_id="altitude_bounds",
            severity=Severity.WARNING,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                f"altitudes within sanity bounds [{ALTITUDE_MIN_KM}, {ALTITUDE_MAX_KM}] km"
                if passed
                else "one or more altitudes outside sanity bounds (possible decay/bad epoch)"
            ),
            values={
                "min_bound_km": ALTITUDE_MIN_KM,
                "max_bound_km": ALTITUDE_MAX_KM,
                "out_of_bounds_count": len(bad),
            },
        )

    @staticmethod
    def _check_propagation_errors(result: ScientificResult) -> VerificationFinding:
        errors = [
            {"index": i, "error": s.error}
            for i, s in enumerate(result.samples)
            if s.status is SampleStatus.ERROR
        ]
        passed = not errors
        return VerificationFinding(
            check_id="propagation_errors",
            severity=Severity.ERROR,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                "no propagation errors"
                if passed
                else f"{len(errors)} sample(s) failed to propagate"
            ),
            values={"errors": errors},
        )

    @staticmethod
    def _check_unit_consistency(result: ScientificResult) -> VerificationFinding:
        missing = [k for k in UNITS if k not in result.units]
        passed = not missing
        return VerificationFinding(
            check_id="unit_consistency",
            severity=Severity.WARNING,
            status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
            explanation=(
                "all expected unit labels are present" if passed else "missing expected unit labels"
            ),
            values={"missing_units": missing},
        )

    @staticmethod
    def _check_provenance_completeness(result: ScientificResult) -> VerificationFinding:
        src = result.source
        complete = bool(src.source_name and src.checksum and src.epoch_utc)
        return VerificationFinding(
            check_id="provenance_completeness",
            severity=Severity.ERROR,
            status=FindingStatus.PASSED if complete else FindingStatus.FAILED,
            explanation=(
                "source provenance is complete" if complete else "source provenance is incomplete"
            ),
            values={
                "source_name": src.source_name,
                "test_only": src.test_only,
                "has_checksum": bool(src.checksum),
            },
        )
