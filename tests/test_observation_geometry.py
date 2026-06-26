"""Domain-only tests for bounded deterministic observation geometry.

The TLE fixture is the repository's pinned ISS sample from the python-sgp4/Vallado
reference example. It is stale, test-only data and is not live satellite truth.
"""

from __future__ import annotations

import ast
import datetime as dt
import math
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.errors import ValidationError
from orbitmind.core.units import WGS84_A_KM, WGS84_B_KM
from orbitmind.observation_geometry import service, verification
from orbitmind.observation_geometry.geodesy import (
    enu_to_azimuth_elevation_range,
    geodetic_to_ecef_km,
    relative_ecef_to_enu_km,
)
from orbitmind.observation_geometry.models import (
    COARSE_SAMPLING_LIMITATION,
    ComputedVisibilityInterval,
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GeometrySample,
    GeometrySampleStatus,
    GroundObservationSite,
    PinnedOrbitElementSet,
    VisibilityRefinementStatus,
)
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.observation_geometry.verification import (
    verify_geometry_result,
    verify_sgp4_reference_vector,
)
from orbitmind.sources.registry import SourceRegistry

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _site(*, latitude: float = 0.0, longitude: float = 0.0) -> GroundObservationSite:
    return GroundObservationSite(
        site_id="SITE-001",
        name="Equator test site",
        position=GeodeticPosition(
            latitude_deg=latitude,
            longitude_deg=longitude,
            altitude_km=0.0,
        ),
    )


def _request(
    *,
    start: dt.datetime = START,
    end: dt.datetime = START + dt.timedelta(minutes=25),
    step_seconds: int = 300,
    minimum_elevation_deg: float = 0.0,
    site: GroundObservationSite | None = None,
) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=site or _site(),
        start=start,
        end=end,
        step_seconds=step_seconds,
        minimum_elevation_deg=minimum_elevation_deg,
    )


def _fix_tle_checksum(line: str) -> str:
    total = 0
    for char in line[:68]:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return f"{line[:68]}{total % 10}"


def test_valid_pinned_tle_has_epoch_and_deterministic_checksum() -> None:
    elements = _registry_elements()
    again = _registry_elements()
    assert elements.element_checksum == again.element_checksum
    assert elements.orbit_epoch == dt.datetime(2019, 12, 9, 16, 38, 29, 363424, tzinfo=UTC)
    assert elements.source.test_only is True


def test_malformed_tle_invalid_checksum_and_unpropagatable_tle_rejected() -> None:
    elements = _registry_elements()
    with pytest.raises(PydanticValidationError):
        PinnedOrbitElementSet(
            source=elements.source,
            tle_line1=elements.tle_line1[:-1],
            tle_line2=elements.tle_line2,
        )
    with pytest.raises(PydanticValidationError, match="checksum"):
        PinnedOrbitElementSet(
            source=elements.source,
            tle_line1=f"{elements.tle_line1[:68]}0",
            tle_line2=elements.tle_line2,
        )
    unpropagatable = _fix_tle_checksum(
        f"{elements.tle_line2[:26]}9999999{elements.tle_line2[33:68]}0"
    )
    with pytest.raises(PydanticValidationError, match="propagatable"):
        PinnedOrbitElementSet(
            source=elements.source,
            tle_line1=elements.tle_line1,
            tle_line2=unpropagatable,
        )
    bad_line_number = _fix_tle_checksum(f"9{elements.tle_line1[1:68]}0")
    with pytest.raises(PydanticValidationError, match="line numbers"):
        PinnedOrbitElementSet(
            source=elements.source,
            tle_line1=bad_line_number,
            tle_line2=elements.tle_line2,
        )
    with pytest.raises(PydanticValidationError, match="element_checksum"):
        PinnedOrbitElementSet(
            source=elements.source,
            tle_line1=elements.tle_line1,
            tle_line2=elements.tle_line2,
            element_checksum="0" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude_deg", 91.0),
        ("longitude_deg", 181.0),
        ("altitude_km", 10.0),
    ],
)
def test_invalid_geodetic_bounds(field: str, value: float) -> None:
    payload = {"latitude_deg": 0.0, "longitude_deg": 0.0, "altitude_km": 0.0}
    payload[field] = value
    with pytest.raises(PydanticValidationError):
        GeodeticPosition(**payload)


def test_request_bounds_and_strict_models(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(PydanticValidationError, match="timezone-aware"):
        _request(start=dt.datetime(2019, 12, 9, 19, 50), end=START + dt.timedelta(minutes=1))
    with pytest.raises(PydanticValidationError, match="after start"):
        _request(start=START, end=START)
    with pytest.raises(PydanticValidationError, match="86400"):
        _request(end=START + dt.timedelta(days=2))
    with pytest.raises(PydanticValidationError):
        _request(step_seconds=0)
    with pytest.raises(PydanticValidationError):
        _request(step_seconds=3_601)
    with pytest.raises(PydanticValidationError):
        _request(minimum_elevation_deg=90.0)
    with pytest.raises(PydanticValidationError):
        GeodeticPosition(latitude_deg=0, longitude_deg=0, altitude_km=0, unknown=True)  # type: ignore[call-arg]
    with pytest.raises(PydanticValidationError):
        _request().model_copy(update={"schema_version": "2"})
        GeometryComputationRequest(
            schema_version="2",  # type: ignore[arg-type]
            elements=_registry_elements(),
            site=_site(),
            start=START,
            end=START + dt.timedelta(minutes=1),
            step_seconds=60,
        )
    monkeypatch.setattr("orbitmind.observation_geometry.models.MAX_PRIMARY_SAMPLES", 3)
    with pytest.raises(PydanticValidationError, match="sample count"):
        _request(end=START + dt.timedelta(minutes=10), step_seconds=60)
    monkeypatch.setattr("orbitmind.observation_geometry.models.MAX_PRIMARY_SAMPLES", 100_000)
    with pytest.raises(PydanticValidationError, match="refinement work"):
        _request(start=START, end=START + dt.timedelta(days=1), step_seconds=1)
    request = _request()
    with pytest.raises(PydanticValidationError, match="request_checksum"):
        GeometryComputationRequest(
            elements=_registry_elements(),
            site=_site(),
            start=START,
            end=START + dt.timedelta(minutes=1),
            step_seconds=60,
            request_checksum="0" * 64,
        )
    no_name_site = GroundObservationSite(site_id="SITE-NO-NAME", position=request.site.position)
    assert no_name_site.name is None
    with pytest.raises(PydanticValidationError, match="unpadded"):
        GroundObservationSite(site_id=" padded ", position=request.site.position)
    with pytest.raises(PydanticValidationError):
        request.site.position.latitude_deg = 1.0  # type: ignore[misc]


def test_sample_interval_and_result_validator_defenses(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamp = START
    with pytest.raises(PydanticValidationError, match="requires all geometry"):
        GeometrySample(timestamp=timestamp, status=GeometrySampleStatus.OK)
    with pytest.raises(PydanticValidationError, match="positive"):
        GeometrySample(
            timestamp=timestamp,
            status=GeometrySampleStatus.OK,
            azimuth_deg=0.0,
            elevation_deg=0.0,
            slant_range_km=0.0,
        )
    with pytest.raises(PydanticValidationError, match="must not include"):
        GeometrySample(
            timestamp=timestamp,
            status=GeometrySampleStatus.OK,
            azimuth_deg=0.0,
            elevation_deg=0.0,
            slant_range_km=1.0,
            safe_error_code="sgp4_status_1",
        )
    with pytest.raises(PydanticValidationError, match="must not fabricate"):
        GeometrySample(
            timestamp=timestamp,
            status=GeometrySampleStatus.ERROR,
            azimuth_deg=0.0,
            safe_error_code="sgp4_status_1",
        )
    with pytest.raises(PydanticValidationError, match="requires a bounded"):
        GeometrySample(timestamp=timestamp, status=GeometrySampleStatus.ERROR)
    with pytest.raises(PydanticValidationError, match="bounded"):
        GeometrySample(
            timestamp=timestamp,
            status=GeometrySampleStatus.ERROR,
            safe_error_code=" padded ",
        )
    with pytest.raises(PydanticValidationError, match="set_time"):
        ComputedVisibilityInterval(
            rise_time=timestamp,
            set_time=timestamp - dt.timedelta(seconds=1),
            peak_time=timestamp,
            peak_elevation_deg=1.0,
            rise_azimuth_deg=0.0,
            set_azimuth_deg=1.0,
        )
    with pytest.raises(PydanticValidationError, match="peak_time"):
        ComputedVisibilityInterval(
            rise_time=timestamp,
            set_time=timestamp + dt.timedelta(seconds=1),
            peak_time=timestamp + dt.timedelta(seconds=2),
            peak_elevation_deg=1.0,
            rise_azimuth_deg=0.0,
            set_azimuth_deg=1.0,
        )

    result = compute_observation_geometry(_request())
    payload = result.model_dump(mode="python")
    for field, value, message in [
        ("sample_count", result.sample_count + 1, "sample_count"),
        ("failed_sample_count", result.failed_sample_count + 1, "failed_sample_count"),
        ("geometry_checksum", "0" * 64, "geometry_checksum"),
        ("request_checksum", "not-a-sha", "String should have at least"),
    ]:
        bad = dict(payload)
        bad[field] = value
        with pytest.raises(PydanticValidationError, match=message):
            GeometryComputationResult.model_validate(bad)
    bad_limitations = dict(payload)
    bad_limitations["limitations"] = ()
    with pytest.raises(PydanticValidationError, match="limitations"):
        GeometryComputationResult.model_validate(bad_limitations)
    forbidden_limitations = dict(payload)
    forbidden_limitations["limitations"] = ("verified satellite access", COARSE_SAMPLING_LIMITATION)
    with pytest.raises(PydanticValidationError, match="operational"):
        GeometryComputationResult.model_validate(forbidden_limitations)
    missing_sampling = dict(payload)
    missing_sampling["limitations"] = ("Deterministic geometry from pinned TLE input",)
    with pytest.raises(PydanticValidationError, match="coarse-sampling"):
        GeometryComputationResult.model_validate(missing_sampling)
    monkeypatch.setattr("orbitmind.observation_geometry.models.MAX_VISIBILITY_INTERVALS", 0)
    with pytest.raises(PydanticValidationError, match="interval count"):
        GeometryComputationResult.model_validate(payload)


def test_geodesy_known_points_and_topocentric_vectors() -> None:
    equator = geodetic_to_ecef_km(GeodeticPosition(latitude_deg=0, longitude_deg=0))
    assert equator == pytest.approx((WGS84_A_KM, 0.0, 0.0), abs=1e-9)
    pole = geodetic_to_ecef_km(GeodeticPosition(latitude_deg=90, longitude_deg=0))
    assert pole[2] == pytest.approx(WGS84_B_KM, rel=0, abs=1e-6)
    assert relative_ecef_to_enu_km(
        (0.0, 1.0, 0.0), GeodeticPosition(latitude_deg=0, longitude_deg=0)
    ) == pytest.approx((1.0, 0.0, 0.0))
    for enu, azimuth, elevation in [
        ((0.0, 1.0, 0.0), 0.0, 0.0),
        ((1.0, 0.0, 0.0), 90.0, 0.0),
        ((0.0, -1.0, 0.0), 180.0, 0.0),
        ((-1.0, 0.0, 0.0), 270.0, 0.0),
        ((0.0, 0.0, 1.0), 0.0, 90.0),
        ((0.0, 1.0, -1.0), 0.0, -45.0),
    ]:
        got_azimuth, got_elevation, slant_range = enu_to_azimuth_elevation_range(enu)
        assert got_azimuth == pytest.approx(azimuth)
        assert got_elevation == pytest.approx(elevation)
        assert slant_range > 0.0
    with pytest.raises(ValueError, match="positive"):
        enu_to_azimuth_elevation_range((0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="finite"):
        relative_ecef_to_enu_km(
            (math.nan, 0.0, 0.0), GeodeticPosition(latitude_deg=0, longitude_deg=0)
        )


def test_geometry_service_is_deterministic_and_ranges_are_valid() -> None:
    request = _request()
    first = compute_observation_geometry(request)
    second = compute_observation_geometry(request)
    assert first.geometry_checksum == second.geometry_checksum
    assert first.request_checksum == request.request_checksum == second.request_checksum
    assert first.intervals
    assert COARSE_SAMPLING_LIMITATION in first.limitations
    assert verify_geometry_result(first, request=request).passed
    for sample in first.samples:
        if sample.status is GeometrySampleStatus.OK:
            assert sample.azimuth_deg is not None and 0.0 <= sample.azimuth_deg < 360.0
            assert sample.elevation_deg is not None and -90.0 <= sample.elevation_deg <= 90.0
            assert sample.slant_range_km is not None and sample.slant_range_km > 0.0


def test_utc_equivalent_request_has_same_checksum() -> None:
    utc_request = _request(start=START, end=START + dt.timedelta(minutes=25))
    offset = dt.timezone(dt.timedelta(hours=5, minutes=30))
    offset_request = _request(
        start=START.astimezone(offset),
        end=(START + dt.timedelta(minutes=25)).astimezone(offset),
    )
    assert utc_request.start == offset_request.start
    assert utc_request.request_checksum == offset_request.request_checksum


def test_propagation_error_sample_has_safe_code(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_once(*args: object, **kwargs: object) -> tuple[int, tuple[float, float, float] | None]:
        return (6, None)

    monkeypatch.setattr(service, "_sgp4_position_km", fail_once)
    result = compute_observation_geometry(_request(end=START + dt.timedelta(minutes=5)))
    assert result.failed_sample_count == result.sample_count
    assert result.intervals == ()
    assert all(sample.safe_error_code == "sgp4_status_6" for sample in result.samples)
    assert "division" not in result.geometry_checksum


def test_visibility_intervals_cover_none_one_many_and_clipped_boundaries() -> None:
    none = compute_observation_geometry(_request(minimum_elevation_deg=89.0))
    assert none.intervals == ()
    one = compute_observation_geometry(_request())
    assert len(one.intervals) == 1
    interval = one.intervals[0]
    assert not interval.rise_boundary_clipped
    assert not interval.set_boundary_clipped
    assert interval.rise_time <= interval.peak_time <= interval.set_time
    many = compute_observation_geometry(
        _request(end=START + dt.timedelta(hours=24), step_seconds=600)
    )
    assert len(many.intervals) > 1
    clipped_start = compute_observation_geometry(
        _request(
            start=dt.datetime(2019, 12, 9, 20, 0, tzinfo=UTC),
            end=dt.datetime(2019, 12, 9, 20, 15, tzinfo=UTC),
            step_seconds=60,
        )
    )
    assert clipped_start.intervals[0].rise_boundary_clipped is True
    clipped_end = compute_observation_geometry(
        _request(
            start=dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC),
            end=dt.datetime(2019, 12, 9, 20, 0, tzinfo=UTC),
            step_seconds=60,
        )
    )
    assert clipped_end.intervals[0].set_boundary_clipped is True


def test_failed_sample_breaks_visibility_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    original = service._sgp4_position_km
    fail_at = dt.datetime(2019, 12, 9, 20, 2, tzinfo=UTC)

    def fail_midpoint(
        satrec: object,
        timestamp: dt.datetime,
    ) -> tuple[int, tuple[float, float, float] | None]:
        if timestamp == fail_at:
            return (6, None)
        return original(satrec, timestamp)  # type: ignore[arg-type]

    monkeypatch.setattr(service, "_sgp4_position_km", fail_midpoint)
    result = compute_observation_geometry(
        _request(
            start=dt.datetime(2019, 12, 9, 20, 0, tzinfo=UTC),
            end=dt.datetime(2019, 12, 9, 20, 5, tzinfo=UTC),
            step_seconds=60,
        )
    )
    assert any(
        sample.timestamp == fail_at
        for sample in result.samples
        if sample.status is GeometrySampleStatus.ERROR
    )
    assert verify_geometry_result(
        result,
        request=_request(
            start=dt.datetime(2019, 12, 9, 20, 0, tzinfo=UTC),
            end=dt.datetime(2019, 12, 9, 20, 5, tzinfo=UTC),
            step_seconds=60,
        ),
    ).passed


def test_visibility_bounds_raise_typed_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "MAX_VISIBILITY_INTERVALS", 0)
    with pytest.raises(ValidationError, match="interval count"):
        compute_observation_geometry(_request())
    monkeypatch.setattr(service, "MAX_VISIBILITY_INTERVALS", 1_024)
    monkeypatch.setattr(service, "MAX_TOTAL_REFINEMENT_EVALUATIONS", 0)
    with pytest.raises(ValidationError, match="refinement"):
        compute_observation_geometry(_request())


def test_refinement_failure_and_private_status_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request(
        start=dt.datetime(2019, 12, 9, 20, 0, tzinfo=UTC),
        end=dt.datetime(2019, 12, 9, 20, 5, tzinfo=UTC),
        step_seconds=60,
    )
    visible = GeometrySample(
        timestamp=request.start + dt.timedelta(seconds=60),
        status=GeometrySampleStatus.OK,
        azimuth_deg=10.0,
        elevation_deg=1.0,
        slant_range_km=500.0,
    )
    below = GeometrySample(
        timestamp=request.start,
        status=GeometrySampleStatus.OK,
        azimuth_deg=9.0,
        elevation_deg=-1.0,
        slant_range_km=501.0,
    )

    def fail_midpoint(*args: object, **kwargs: object) -> service._PropagationOutcome:
        return service._PropagationOutcome(
            GeometrySample(
                timestamp=request.start + dt.timedelta(seconds=30),
                status=GeometrySampleStatus.ERROR,
                safe_error_code="sgp4_status_6",
            )
        )

    monkeypatch.setattr(service, "_propagate_look_angle", fail_midpoint)
    boundary, used = service._refine_crossing(
        object(),  # type: ignore[arg-type]
        request,
        below,
        visible,
        rising=True,
        evaluations_so_far=0,
    )
    assert used == 1
    assert boundary.status is VisibilityRefinementStatus.REFINEMENT_FAILED
    sampled, sampled_used = service._refine_crossing(
        object(),  # type: ignore[arg-type]
        request,
        visible,
        visible,
        rising=True,
        evaluations_so_far=0,
    )
    assert sampled.sample == visible
    assert sampled_used == 0
    assert (
        service._combined_refinement_status(
            VisibilityRefinementStatus.CLIPPED,
            VisibilityRefinementStatus.SAMPLED,
        )
        is VisibilityRefinementStatus.SAMPLED
    )


def test_sgp4_status_error_branch_is_safe() -> None:
    class FakeSatrec:
        def sgp4(
            self,
            jd: float,
            fr: float,
        ) -> tuple[int, tuple[float, float, float], tuple[float, float, float]]:
            return (6, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))

    error_code, position = service._sgp4_position_km(FakeSatrec(), START)  # type: ignore[arg-type]
    assert error_code == 6
    assert position is None


def test_verification_detects_tampering() -> None:
    request = _request()
    result = compute_observation_geometry(request)
    assert verify_geometry_result(result, request=request).passed
    assert verify_geometry_result(result).passed
    mutations = [
        result.model_copy(update={"request_checksum": "0" * 64}),
        result.model_copy(update={"geometry_checksum": "0" * 64}),
        result.model_copy(update={"samples": tuple(reversed(result.samples))}),
        result.model_copy(
            update={
                "samples": (
                    result.samples[0].model_copy(update={"azimuth_deg": 999.0}),
                    *result.samples[1:],
                )
            }
        ),
        result.model_copy(
            update={
                "samples": (
                    result.samples[0].model_copy(update={"elevation_deg": 999.0}),
                    *result.samples[1:],
                )
            }
        ),
        result.model_copy(
            update={
                "samples": (
                    result.samples[0].model_copy(update={"slant_range_km": 0.0}),
                    *result.samples[1:],
                )
            }
        ),
        result.model_copy(
            update={
                "samples": (
                    result.samples[0].model_copy(
                        update={
                            "status": GeometrySampleStatus.ERROR,
                            "safe_error_code": "sgp4_status_6",
                        }
                    ),
                    *result.samples[1:],
                )
            }
        ),
        result.model_copy(update={"schema_version": "2"}),
    ]
    for mutated in mutations:
        assert not verify_geometry_result(mutated, request=request).passed


def test_verification_detects_interval_tampering() -> None:
    request = _request()
    result = compute_observation_geometry(request)
    interval = result.intervals[0]
    outside = interval.model_copy(update={"rise_time": request.start - dt.timedelta(seconds=1)})
    overlapping = result.model_copy(update={"intervals": (interval, interval)})
    failed_sample = result.samples[0].model_copy(
        update={"status": GeometrySampleStatus.ERROR, "safe_error_code": "sgp4_status_6"}
    )
    spanning_failure = result.model_copy(update={"samples": (failed_sample, *result.samples[1:])})
    assert not verify_geometry_result(
        result.model_copy(update={"intervals": (outside,)}), request=request
    ).passed
    assert not verify_geometry_result(overlapping, request=request).passed
    assert not verify_geometry_result(spanning_failure, request=request).passed
    empty_inside = result.model_copy(
        update={
            "intervals": (
                interval.model_copy(
                    update={
                        "rise_time": request.start + dt.timedelta(seconds=1),
                        "set_time": request.start + dt.timedelta(seconds=2),
                        "peak_time": request.start + dt.timedelta(seconds=1),
                    }
                ),
            )
        }
    )
    assert not verify_geometry_result(empty_inside, request=request).passed
    malformed = result.model_copy(
        update={
            "samples": (
                result.samples[0].model_copy(
                    update={
                        "azimuth_deg": "not-a-float",
                        "elevation_deg": 0.0,
                        "slant_range_km": 1.0,
                    }
                ),
                *result.samples[1:],
            )
        }
    )
    assert not verify_geometry_result(malformed, request=request).passed


def test_vallado_reference_vector_within_tolerance() -> None:
    elements = _registry_elements()
    verification = verify_sgp4_reference_vector(
        elements,
        timestamp=dt.datetime(2019, 12, 9, 17, 0, 0, tzinfo=UTC),
        expected_teme_km=(5520.62920478, 3920.766382868, -634.621738414),
        tolerance_km=1e-6,
    )
    assert verification.passed


def test_reference_vector_error_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_reference(*args: object, **kwargs: object) -> tuple[int, None]:
        return (6, None)

    monkeypatch.setattr(verification, "_sgp4_position_km", fail_reference)
    result = verify_sgp4_reference_vector(
        _registry_elements(),
        timestamp=dt.datetime(2019, 12, 9, 17, 0, 0, tzinfo=UTC),
        expected_teme_km=(0.0, 0.0, 0.0),
        tolerance_km=1e-6,
    )
    assert not result.passed


def test_no_forbidden_architecture_imports() -> None:
    package = Path("src/orbitmind/observation_geometry")
    forbidden_prefixes = (
        "orbitmind.api",
        "orbitmind.persistence",
        "orbitmind.observation_planning",
        "orbitmind.quantum",
        "httpx",
        "requests",
    )
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = _imported_module(node)
            if module is not None:
                assert not module.startswith(forbidden_prefixes), (path, module)


def test_result_models_expose_no_orm_rows() -> None:
    result = compute_observation_geometry(_request())
    assert not isinstance(result, ModuleType)
    assert "sqlalchemy" not in repr(type(result)).lower()
    assert "session" not in result.model_dump_json().lower()


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
