"""Unit tests for deterministic SGP4 propagation + geodesy."""

from __future__ import annotations

import datetime as dt
import math

from orbitmind.mission.models import MissionRequest, OutputType
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.models import SampleStatus
from orbitmind.space.propagation import PropagationService

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 17, 0, 0, tzinfo=UTC)


def _request() -> MissionRequest:
    return MissionRequest(
        satellite_id="ISS",
        start_time=START,
        end_time=START + dt.timedelta(hours=1),
        step_seconds=120,
        output_types=list(OutputType),
    )


def _propagate() -> object:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PropagationService().propagate(
        mission_id="00000000-0000-0000-0000-000000000000",
        request=_request(),
        source=source,
        tle_line1=line1,
        tle_line2=line2,
    )


def test_sample_count_matches_expected() -> None:
    result = _propagate()
    assert len(result.samples) == _request().expected_sample_count() == 31  # type: ignore[attr-defined]


def test_iss_altitude_is_physically_reasonable() -> None:
    result = _propagate()
    for s in result.samples:  # type: ignore[attr-defined]
        assert s.status is SampleStatus.OK
        assert 380.0 < s.altitude_km < 450.0  # ISS LEO band
        assert -52.0 <= s.latitude_deg <= 52.0  # ISS inclination ~51.6 deg
        assert -180.0 <= s.longitude_deg <= 180.0


def test_position_magnitude_near_earth_radius_plus_altitude() -> None:
    result = _propagate()
    s = result.samples[0]  # type: ignore[attr-defined]
    r = math.sqrt(s.position_km.x**2 + s.position_km.y**2 + s.position_km.z**2)
    assert 6700.0 < r < 6900.0  # ~6378 km Earth radius + ~420 km altitude


def test_propagation_is_deterministic() -> None:
    a = _propagate()
    b = _propagate()
    for sa, sb in zip(a.samples, b.samples, strict=True):  # type: ignore[attr-defined]
        assert sa.altitude_km == sb.altitude_km
        assert sa.latitude_deg == sb.latitude_deg
        assert sa.longitude_deg == sb.longitude_deg


def test_software_versions_recorded() -> None:
    result = _propagate()
    versions = result.software_versions  # type: ignore[attr-defined]
    assert "sgp4" in versions
    assert versions["sgp4"] != "unknown"


def test_summary_has_altitude_stats() -> None:
    result = _propagate()
    summary = result.summary  # type: ignore[attr-defined]
    assert summary["sample_count"] == 31
    assert summary["error_count"] == 0
    assert "altitude_min_km" in summary and "altitude_max_km" in summary
