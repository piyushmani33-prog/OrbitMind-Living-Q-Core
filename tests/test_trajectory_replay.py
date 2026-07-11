"""Focused scientific tests for the deterministic offline trajectory replay projection."""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError as PydanticValidationError

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.checksums import sha256_file
from orbitmind.core.errors import ValidationError
from orbitmind.mission_windows.models import MissionWindowRequest, ObserverLocation
from orbitmind.mission_windows.service import MissionWindowService
from orbitmind.observation_geometry.models import GeodeticPosition, PinnedOrbitElementSet
from orbitmind.sources.registry import SourceRegistry
from orbitmind.trajectory_replay.models import (
    PINNED_MODEL_STATEMENT,
    PREDICTED_REPLAY_LIMITATION,
    TRAJECTORY_REPLAY_LIMITATIONS,
    TrajectoryReplayRequest,
    TrajectoryReplaySample,
    TrajectoryTrackSegmentStartReason,
)
from orbitmind.trajectory_replay.service import (
    TrajectoryProjection,
    TrajectoryReplayService,
    segment_ground_track,
)

START = datetime(2019, 12, 9, 16, 38, 29, 363424, tzinfo=UTC)
REFERENCE_PATH = (
    Path(__file__).parent / "fixtures" / "trajectory_replay" / "iss_wgs84_reference.json"
)
MISSION_WINDOW_REFERENCE_PATH = (
    Path(__file__).parent / "fixtures" / "mission_windows" / "iss_equator_reference.json"
)


def _elements(*, changed_source: bool = False) -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    if changed_source:
        source = source.model_copy(
            update={
                "satellite_id": "ISS_ALT",
                "checksum": "a" * 64,
            }
        )
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _request(
    *,
    elements: PinnedOrbitElementSet | None = None,
    start: datetime = START,
    end: datetime = START + timedelta(minutes=2),
    sample_interval_seconds: int = 60,
    observer: GeodeticPosition | None = None,
    maximum_samples: int = 2_001,
    **updates: Any,
) -> TrajectoryReplayRequest:
    return TrajectoryReplayRequest(
        orbital_source=elements or _elements(),
        trajectory_reference="bundled-tle:ISS",
        start_time=start,
        end_time=end,
        sample_interval_seconds=sample_interval_seconds,
        observer=observer,
        maximum_samples=maximum_samples,
        **updates,
    )


def _analytic_sample(sequence: int, longitude: float) -> TrajectoryReplaySample:
    return TrajectoryReplaySample(
        sequence=sequence,
        timestamp=START + timedelta(seconds=sequence),
        latitude_deg=10.0,
        longitude_deg=longitude,
        altitude_km=400.0,
    )


def test_request_is_frozen_strict_utc_and_endpoint_bounded() -> None:
    request = _request()

    assert request.start_time.tzinfo is UTC
    assert request.end_time.tzinfo is UTC
    assert request.expected_sample_count() == 3
    with pytest.raises(PydanticValidationError):
        request.sample_interval_seconds = 30  # type: ignore[misc]
    with pytest.raises(PydanticValidationError):
        TrajectoryReplayRequest(
            **request.model_dump(),
            unexpected=True,  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "factory",
    [
        lambda: _request(start=START.replace(tzinfo=None)),
        lambda: _request(end=START),
        lambda: _request(end=START + timedelta(hours=24, microseconds=1)),
        lambda: _request(sample_interval_seconds=0),
        lambda: _request(sample_interval_seconds=301),
        lambda: _request(maximum_samples=1),
    ],
)
def test_invalid_request_bounds_are_rejected(
    factory: Callable[[], TrajectoryReplayRequest],
) -> None:
    with pytest.raises(PydanticValidationError):
        factory()


def test_sample_limit_overflow_is_rejected_before_service_construction() -> None:
    with pytest.raises(PydanticValidationError, match="explicit sample bound"):
        _request(
            end=START + timedelta(seconds=2_001),
            sample_interval_seconds=1,
        )
    with pytest.raises(PydanticValidationError, match="explicit sample bound"):
        _request(end=START + timedelta(minutes=3), maximum_samples=3)


def test_sampling_includes_exact_end_once_without_float_accumulation() -> None:
    request = _request(end=START + timedelta(seconds=125))
    result = TrajectoryReplayService().calculate(request)

    assert tuple(sample.timestamp for sample in result.samples) == (
        START,
        START + timedelta(seconds=60),
        START + timedelta(seconds=120),
        START + timedelta(seconds=125),
    )
    assert len({sample.timestamp for sample in result.samples}) == 4
    assert result.sample_count == request.expected_sample_count() == 4


def test_fixed_input_is_serially_and_referentially_deterministic() -> None:
    request = _request(end=START + timedelta(minutes=5), sample_interval_seconds=100)
    service = TrajectoryReplayService()

    first = service.calculate(request)
    second = service.calculate(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.input_reference == second.input_reference
    assert first.result_reference == second.result_reference


def test_scientific_input_changes_change_input_reference() -> None:
    baseline = _request()
    variants = (
        _request(elements=_elements(changed_source=True)),
        _request(end=START + timedelta(minutes=3)),
        _request(sample_interval_seconds=30),
        _request(observer=GeodeticPosition(latitude_deg=1, longitude_deg=2, altitude_km=0)),
    )

    assert len({baseline.input_reference, *(variant.input_reference for variant in variants)}) == 5


def test_samples_are_finite_geodetic_and_source_offsets_are_exact() -> None:
    request = _request(end=START + timedelta(minutes=20), sample_interval_seconds=300)
    result = TrajectoryReplayService().calculate(request)

    assert result.source_identity.source_epoch == START
    assert result.source_start_offset_seconds == 0.0
    assert result.source_end_offset_seconds == 1_200.0
    for sample in result.samples:
        assert math.isfinite(sample.latitude_deg)
        assert math.isfinite(sample.longitude_deg)
        assert math.isfinite(sample.altitude_km)
        assert -90.0 <= sample.latitude_deg <= 90.0
        assert -180.0 <= sample.longitude_deg < 180.0


def test_optional_observer_projection_is_complete_and_bounded() -> None:
    observer = GeodeticPosition(latitude_deg=28.6139, longitude_deg=77.209, altitude_km=0.216)
    result = TrajectoryReplayService().calculate(_request(observer=observer))

    assert result.observer == observer
    for sample in result.samples:
        assert sample.observer_azimuth_deg is not None
        assert sample.observer_elevation_deg is not None
        assert sample.observer_slant_range_km is not None
        assert 0.0 <= sample.observer_azimuth_deg < 360.0
        assert -90.0 <= sample.observer_elevation_deg <= 90.0
        assert sample.observer_slant_range_km > 0.0


def test_sample_contract_rejects_noncanonical_or_nonfinite_values() -> None:
    with pytest.raises(PydanticValidationError):
        _analytic_sample(0, 180.0)
    with pytest.raises(PydanticValidationError):
        TrajectoryReplaySample(
            sequence=0,
            timestamp=START,
            latitude_deg=0,
            longitude_deg=0,
            altitude_km=float("nan"),
        )
    with pytest.raises(PydanticValidationError, match="present or absent together"):
        TrajectoryReplaySample(
            sequence=0,
            timestamp=START,
            latitude_deg=0,
            longitude_deg=0,
            altitude_km=400,
            observer_azimuth_deg=10,
        )


@pytest.mark.parametrize(
    ("longitudes", "expected_segments"),
    [
        ((179.5, -179.7), ((0,), (1,))),
        ((-179.5, 179.7), ((0,), (1,))),
        ((170.0, 175.0, 179.0), ((0, 1, 2),)),
    ],
)
def test_dateline_segmentation_is_direction_safe_and_has_no_false_split(
    longitudes: tuple[float, ...],
    expected_segments: tuple[tuple[int, ...], ...],
) -> None:
    samples = tuple(
        _analytic_sample(sequence, longitude) for sequence, longitude in enumerate(longitudes)
    )

    segments = segment_ground_track(samples)

    assert tuple(segment.sample_indexes for segment in segments) == expected_segments
    assert segments[0].start_reason is TrajectoryTrackSegmentStartReason.REQUEST_START
    assert all(
        segment.start_reason is TrajectoryTrackSegmentStartReason.DATELINE_WRAP
        for segment in segments[1:]
    )
    flattened = tuple(index for segment in segments for index in segment.sample_indexes)
    assert flattened == tuple(range(len(samples)))
    assert len(set(flattened)) == len(samples)


def test_segmentation_is_deterministic_and_requires_ordered_sequence() -> None:
    samples = tuple(
        _analytic_sample(sequence, longitude)
        for sequence, longitude in enumerate((10.0, 20.0, 179.0, -179.0, -170.0))
    )

    assert segment_ground_track(samples) == segment_ground_track(samples)
    with pytest.raises(ValueError, match="contiguous sample sequence"):
        segment_ground_track((samples[0], samples[2]))


class _FailingEvaluator:
    def __init__(self, fail_on_call: int) -> None:
        self.fail_on_call = fail_on_call
        self.timestamps: list[datetime] = []

    def evaluate(self, timestamp: datetime) -> TrajectoryProjection:
        self.timestamps.append(timestamp)
        if len(self.timestamps) == self.fail_on_call:
            raise RuntimeError("synthetic private propagation detail")
        return TrajectoryProjection(
            latitude_deg=0.0,
            longitude_deg=float(len(self.timestamps)),
            altitude_km=400.0,
        )


def test_propagation_failure_after_valid_sample_fails_without_partial_result() -> None:
    evaluator = _FailingEvaluator(fail_on_call=2)
    service = TrajectoryReplayService(evaluator_factory=lambda **_kwargs: evaluator)

    with pytest.raises(ValidationError, match="sample calculation failed") as exc_info:
        service.calculate(_request())

    assert evaluator.timestamps == [START, START + timedelta(seconds=60)]
    assert "synthetic private propagation detail" not in str(exc_info.value)


def test_required_limitations_and_safe_serialization_are_fixed() -> None:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS").model_copy(
        update={"source_url": r"C:\private\raw-provider-response.json"}
    )
    line1, line2 = registry.get_tle("ISS")
    elements = PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)
    result = TrajectoryReplayService().calculate(_request(elements=elements))
    serialized = json.dumps(result.model_dump(mode="json"), sort_keys=True)

    assert result.limitations == TRAJECTORY_REPLAY_LIMITATIONS
    assert PREDICTED_REPLAY_LIMITATION in result.limitations
    assert PINNED_MODEL_STATEMENT in result.limitations
    assert line1 not in serialized
    assert line2 not in serialized
    assert source.source_url not in serialized
    assert "100%" not in serialized
    assert "real-time" not in serialized.lower()
    assert "current true location" not in serialized.lower()


def test_service_has_no_api_network_persistence_or_quantum_dependency() -> None:
    package_root = Path(__file__).parents[1] / "src" / "orbitmind" / "trajectory_replay"
    imported: set[str] = set()
    for path in package_root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)

    assert not any(
        module.startswith(
            (
                "orbitmind.api",
                "orbitmind.persistence",
                "orbitmind.sources",
                "orbitmind.quantum",
                "httpx",
                "requests",
            )
        )
        for module in imported
    )


def test_independent_iss_reference_fixture_matches_with_documented_tolerances() -> None:
    fixture = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))
    source_path = Path(__file__).parents[1] / fixture["source_fixture"]
    request_data = fixture["request"]
    request = _request(
        start=_parse_utc(request_data["start_time"]),
        end=_parse_utc(request_data["end_time"]),
        sample_interval_seconds=request_data["sample_interval_seconds"],
    )

    result = TrajectoryReplayService().calculate(request)
    actual_by_time = {_format_utc(sample.timestamp): sample for sample in result.samples}
    tolerances = fixture["tolerances"]

    assert sha256_file(source_path) == fixture["source_fixture_sha256"]
    assert request.orbital_source.element_checksum == fixture["element_checksum"]
    assert result.source_identity.norad_catalog_id == fixture["norad_catalog_id"]
    for expected in fixture["samples"]:
        actual = actual_by_time[expected["timestamp"]]
        assert actual.latitude_deg == pytest.approx(
            expected["latitude_deg"], abs=tolerances["latitude_deg"]
        )
        assert actual.longitude_deg == pytest.approx(
            expected["longitude_deg"], abs=tolerances["longitude_deg"]
        )
        assert actual.altitude_km == pytest.approx(
            expected["altitude_km"], abs=tolerances["altitude_km"]
        )
    assert len(result.track_segments) == 2
    assert result.track_segments[1].sample_indexes[0] == 100


def test_existing_mission_window_reference_remains_unchanged() -> None:
    fixture = json.loads(MISSION_WINDOW_REFERENCE_PATH.read_text(encoding="utf-8"))
    request_data = fixture["request"]
    expected = fixture["expected_window"]
    tolerances = fixture["tolerances"]
    result = MissionWindowService().calculate(
        MissionWindowRequest(
            orbital_source=_elements(),
            trajectory_reference="bundled-tle:ISS",
            observer=ObserverLocation(**fixture["observer"]),
            start_time=_parse_utc(request_data["start_time"]),
            end_time=_parse_utc(request_data["end_time"]),
            minimum_elevation_deg=request_data["minimum_elevation_deg"],
            coarse_step_seconds=60,
        )
    )

    assert result.window_count == 1
    window = result.windows[0]
    assert (
        abs((window.rise_time - _parse_utc(expected["rise_time"])).total_seconds())
        <= (tolerances["event_time_seconds"])
    )
    assert window.maximum_elevation_deg == pytest.approx(
        expected["maximum_elevation_deg"],
        abs=tolerances["maximum_elevation_deg"],
    )


def test_existing_workbench_route_and_calculation_remain_unchanged(
    container: AppContainer,
) -> None:
    form = {
        "source_mode": "catalog",
        "catalog_sample_id": "iss",
        "custom_label": "",
        "tle_line1": "",
        "tle_line2": "",
        "observer_latitude_deg": "0",
        "observer_longitude_deg": "0",
        "observer_altitude_metres": "0",
        "start_time_utc": "2019-12-09T19:40:00Z",
        "duration_hours": "1",
        "minimum_elevation_deg": "0",
    }
    with TestClient(create_app(container)) as client:
        assert client.get("/workbench").status_code == 200
        response = client.post("/workbench/run", data=form)

    assert response.status_code == 200
    assert "Next predicted pass/contact window" in response.text
    assert "Geometric window only; optical visibility is not assessed." in response.text


def test_no_trajectory_replay_api_route_was_added(container: AppContainer) -> None:
    with TestClient(create_app(container)) as client:
        paths = set(client.app.openapi()["paths"])

    assert not any("trajectory-replay" in path for path in paths)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
