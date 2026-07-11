"""Focused tests for the deterministic offline mission-window application service.

The ISS event reference is stored in ``tests/fixtures/mission_windows``. It was generated
by a one-off scalar calculation that used python-sgp4 plus independently written
IAU-1982 GMST, WGS84 ECEF, and ENU equations; it did not import OrbitMind geometry or
mission-window code. Synthetic curves isolate event-search behavior from propagation.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.errors import ValidationError
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.mission_windows.models import (
    GEOMETRIC_ONLY_LIMITATION,
    MAX_MISSION_WINDOW_HORIZON_SECONDS,
    MODEL_STATEMENT,
    MissionWindowCalculationStatus,
    MissionWindowEventClassification,
    MissionWindowRequest,
    ObserverLocation,
)
from orbitmind.mission_windows.service import MissionWindowService
from orbitmind.observation_geometry.models import (
    GeometrySample,
    GeometrySampleStatus,
    PinnedOrbitElementSet,
)
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.propagation import COMPUTATION_VERSION as SGP4_COMPUTATION_VERSION

SYNTHETIC_START = datetime(2026, 7, 11, 0, 0, tzinfo=UTC)
REFERENCE_PATH = (
    Path(__file__).parent / "fixtures" / "mission_windows" / "iss_equator_reference.json"
)


def _elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _request(
    *,
    start: datetime = SYNTHETIC_START,
    end: datetime = SYNTHETIC_START + timedelta(minutes=20),
    observer: ObserverLocation | None = None,
    minimum_elevation_deg: float = 0.0,
    coarse_step_seconds: int = 60,
    **updates: Any,
) -> MissionWindowRequest:
    return MissionWindowRequest(
        orbital_source=_elements(),
        trajectory_reference="bundled-tle:ISS",
        observer=observer or ObserverLocation(latitude_deg=0.0, longitude_deg=0.0),
        start_time=start,
        end_time=end,
        minimum_elevation_deg=minimum_elevation_deg,
        coarse_step_seconds=coarse_step_seconds,
        **updates,
    )


class SyntheticEvaluator:
    def __init__(
        self,
        elevation: Callable[[float], float],
        *,
        fail_at_seconds: float | None = None,
    ) -> None:
        self._elevation = elevation
        self._fail_at_seconds = fail_at_seconds

    def evaluate(self, timestamp: datetime) -> GeometrySample:
        seconds = (timestamp - SYNTHETIC_START).total_seconds()
        if self._fail_at_seconds is not None and math.isclose(
            seconds,
            self._fail_at_seconds,
            abs_tol=1e-9,
        ):
            return GeometrySample(
                timestamp=timestamp,
                status=GeometrySampleStatus.ERROR,
                safe_error_code="synthetic_propagation_failure",
            )
        elevation = max(-89.0, min(89.0, self._elevation(seconds)))
        return GeometrySample(
            timestamp=timestamp,
            status=GeometrySampleStatus.OK,
            azimuth_deg=(seconds * 0.37) % 360.0,
            elevation_deg=elevation,
            slant_range_km=500.0 + abs(seconds) / 100.0,
        )


def _synthetic_service(
    elevation: Callable[[float], float],
    *,
    fail_at_seconds: float | None = None,
) -> MissionWindowService:
    evaluator = SyntheticEvaluator(elevation, fail_at_seconds=fail_at_seconds)

    def factory(**_kwargs: object) -> SyntheticEvaluator:
        return evaluator

    return MissionWindowService(evaluator_factory=factory)


def _parabola(seconds: float, *, peak_time: float, peak_elevation: float, width: float) -> float:
    return peak_elevation - ((seconds - peak_time) / width) ** 2


def _seconds(timestamp: datetime) -> float:
    return (timestamp - SYNTHETIC_START).total_seconds()


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def test_request_is_strict_bounded_utc_and_deterministically_identified() -> None:
    request = _request()
    offset = timezone(timedelta(hours=5, minutes=30))
    same = _request(
        start=request.start_time.astimezone(offset),
        end=request.end_time.astimezone(offset),
    )

    assert request.start_time.tzinfo is UTC
    assert request.end_time.tzinfo is UTC
    assert request.input_reference == same.input_reference
    assert request.trajectory_reference == "bundled-tle:ISS"
    with pytest.raises(PydanticValidationError):
        MissionWindowRequest(**request.model_dump(), unexpected=True)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("latitude_deg", -90.1),
        ("latitude_deg", 90.1),
        ("longitude_deg", -180.1),
        ("longitude_deg", 180.1),
        ("altitude_metres", -500.1),
        ("altitude_metres", 9_000.1),
        ("latitude_deg", math.nan),
        ("longitude_deg", math.inf),
        ("altitude_metres", -math.inf),
    ),
)
def test_observer_rejects_invalid_or_non_finite_coordinates(field: str, value: float) -> None:
    payload = {"latitude_deg": 0.0, "longitude_deg": 0.0, "altitude_metres": 0.0}
    payload[field] = value
    with pytest.raises(PydanticValidationError):
        ObserverLocation(**payload)


def test_request_rejects_invalid_times_horizon_threshold_and_work_bound() -> None:
    naive = datetime(2026, 7, 11, 0, 0)
    with pytest.raises(PydanticValidationError, match="timezone-aware"):
        _request(start=naive)
    with pytest.raises(PydanticValidationError, match="after start"):
        _request(end=SYNTHETIC_START)
    with pytest.raises(PydanticValidationError, match="24 hours"):
        _request(end=SYNTHETIC_START + timedelta(seconds=MAX_MISSION_WINDOW_HORIZON_SECONDS + 1))
    for threshold in (-0.1, 90.0, math.nan, math.inf):
        with pytest.raises(PydanticValidationError):
            _request(minimum_elevation_deg=threshold)
    with pytest.raises(PydanticValidationError, match="coarse-sample bound"):
        _request(end=SYNTHETIC_START + timedelta(hours=24), coarse_step_seconds=5)


def test_no_pass_returns_an_empty_successful_result() -> None:
    result = _synthetic_service(lambda _seconds: -5.0).calculate(_request())

    assert result.calculation_status is MissionWindowCalculationStatus.COMPLETED
    assert result.window_count == 0
    assert result.windows == ()


def test_one_complete_pass_has_refined_boundaries_and_peak() -> None:
    service = _synthetic_service(
        lambda seconds: _parabola(
            seconds,
            peak_time=300.0,
            peak_elevation=25.0,
            width=30.0,
        )
    )
    result = service.calculate(_request(end=SYNTHETIC_START + timedelta(minutes=10)))
    event = result.windows[0]

    assert result.window_count == 1
    assert result.propagation_model == SGP4_COMPUTATION_VERSION
    assert event.classification is MissionWindowEventClassification.COMPLETE
    assert _seconds(event.rise_time) == pytest.approx(150.0, abs=0.1)
    assert _seconds(event.peak_time) == pytest.approx(300.0, abs=0.1)
    assert _seconds(event.set_time) == pytest.approx(450.0, abs=0.1)
    assert event.maximum_elevation_deg == pytest.approx(25.0, abs=1e-5)
    assert event.duration_seconds > 0.0


def test_multiple_passes_are_ordered_non_overlapping_and_unique() -> None:
    def elevation(seconds: float) -> float:
        first = _parabola(seconds, peak_time=300.0, peak_elevation=25.0, width=30.0)
        second = _parabola(seconds, peak_time=900.0, peak_elevation=16.0, width=30.0)
        return max(first, second)

    result = _synthetic_service(elevation).calculate(_request())

    assert result.window_count == 2
    assert result.windows[0].set_time < result.windows[1].rise_time
    assert len({(event.rise_time, event.set_time) for event in result.windows}) == 2


def test_pass_active_at_interval_start_is_explicitly_clipped() -> None:
    result = _synthetic_service(lambda seconds: 10.0 - seconds / 30.0).calculate(
        _request(end=SYNTHETIC_START + timedelta(minutes=10))
    )
    event = result.windows[0]

    assert event.rise_time == SYNTHETIC_START
    assert event.begins_before_requested_interval is True
    assert event.ends_after_requested_interval is False
    assert event.classification is MissionWindowEventClassification.CLIPPED_AT_START


def test_pass_active_at_non_grid_interval_end_is_explicitly_clipped() -> None:
    end = SYNTHETIC_START + timedelta(seconds=605)
    result = _synthetic_service(lambda seconds: (seconds - 300.0) / 30.0).calculate(
        _request(end=end)
    )
    event = result.windows[0]

    assert event.set_time == end
    assert event.begins_before_requested_interval is False
    assert event.ends_after_requested_interval is True
    assert event.classification is MissionWindowEventClassification.CLIPPED_AT_END


def test_window_active_across_entire_interval_is_clipped_at_both_boundaries() -> None:
    request = _request(end=SYNTHETIC_START + timedelta(minutes=5))
    event = _synthetic_service(lambda _seconds: 10.0).calculate(request).windows[0]

    assert event.rise_time == request.start_time
    assert event.set_time == request.end_time
    assert event.classification is MissionWindowEventClassification.CLIPPED_AT_BOTH


def test_exact_threshold_samples_are_stable_and_tangent_contact_is_omitted() -> None:
    def triangular(seconds: float) -> float:
        return 10.0 - abs(seconds - 300.0) / 18.0

    event = (
        _synthetic_service(triangular)
        .calculate(_request(end=SYNTHETIC_START + timedelta(minutes=10)))
        .windows[0]
    )
    tangent = _synthetic_service(lambda seconds: -(((seconds - 300.0) / 30.0) ** 2)).calculate(
        _request(end=SYNTHETIC_START + timedelta(minutes=10))
    )

    assert _seconds(event.rise_time) == pytest.approx(120.0)
    assert _seconds(event.set_time) == pytest.approx(480.0)
    assert tangent.windows == ()


def test_peak_refinement_finds_non_grid_maximum_and_consistent_azimuths() -> None:
    target_peak = 313.25
    result = _synthetic_service(
        lambda seconds: _parabola(
            seconds,
            peak_time=target_peak,
            peak_elevation=30.0,
            width=20.0,
        )
    ).calculate(_request(end=SYNTHETIC_START + timedelta(minutes=10)))
    event = result.windows[0]

    assert _seconds(event.peak_time) == pytest.approx(target_peak, abs=0.1)
    assert event.maximum_elevation_deg == pytest.approx(30.0, abs=1e-5)
    assert event.maximum_elevation_deg >= result.minimum_elevation_deg
    for azimuth in (event.rise_azimuth_deg, event.peak_azimuth_deg, event.set_azimuth_deg):
        assert math.isfinite(azimuth)
        assert 0.0 <= azimuth < 360.0


def test_propagation_failure_inside_interval_fails_closed() -> None:
    service = _synthetic_service(lambda _seconds: 10.0, fail_at_seconds=120.0)

    with pytest.raises(ValidationError, match="geometry evaluation failed"):
        service.calculate(_request(end=SYNTHETIC_START + timedelta(minutes=5)))


def test_fixed_input_produces_identical_typed_and_serialized_output() -> None:
    service = _synthetic_service(
        lambda seconds: _parabola(
            seconds,
            peak_time=300.0,
            peak_elevation=25.0,
            width=30.0,
        )
    )
    request = _request(end=SYNTHETIC_START + timedelta(minutes=10))

    first = service.calculate(request)
    second = service.calculate(request)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.input_reference == request.input_reference
    assert first.result_reference == second.result_reference


def test_result_always_carries_geometric_only_and_no_overclaim_boundaries() -> None:
    result = _synthetic_service(lambda _seconds: -5.0).calculate(_request())
    serialized = result.model_dump_json().casefold()

    assert GEOMETRIC_ONLY_LIMITATION in result.limitations
    assert result.model_statement == MODEL_STATEMENT
    assert result.epistemic_status is EpistemicStatus.DETERMINISTIC_CALCULATION
    for prohibited_claim in (
        "100% accurate",
        "current true position",
        "guaranteed visibility",
        "certified tracking",
        "command ready",
    ):
        assert prohibited_claim not in serialized


def test_bundled_iss_window_matches_independently_generated_reference() -> None:
    fixture = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    request_data = fixture["request"]
    observer_data = fixture["observer"]
    request = _request(
        start=_parse_utc(request_data["start_time"]),
        end=_parse_utc(request_data["end_time"]),
        observer=ObserverLocation(**observer_data),
        minimum_elevation_deg=request_data["minimum_elevation_deg"],
    )

    result = MissionWindowService().calculate(request)
    expected = fixture["expected_window"]
    tolerances = fixture["tolerances"]
    event = result.windows[0]

    assert result.window_count == 1
    for actual, expected_key in (
        (event.rise_time, "rise_time"),
        (event.peak_time, "peak_time"),
        (event.set_time, "set_time"),
    ):
        difference = abs((actual - _parse_utc(expected[expected_key])).total_seconds())
        assert difference <= tolerances["event_time_seconds"]
    assert event.rise_azimuth_deg == pytest.approx(
        expected["rise_azimuth_deg"], abs=tolerances["azimuth_deg"]
    )
    assert event.peak_azimuth_deg == pytest.approx(
        expected["peak_azimuth_deg"], abs=tolerances["azimuth_deg"]
    )
    assert event.set_azimuth_deg == pytest.approx(
        expected["set_azimuth_deg"], abs=tolerances["azimuth_deg"]
    )
    assert event.maximum_elevation_deg == pytest.approx(
        expected["maximum_elevation_deg"],
        abs=tolerances["maximum_elevation_deg"],
    )
    assert result.source_identity.test_only is True
    assert result.source_epoch == datetime(2019, 12, 9, 16, 38, 29, 363424, tzinfo=UTC)
    assert result.prediction_start_offset_seconds is not None
    assert result.prediction_end_offset_seconds is not None
