"""Unit tests for request validation and safety bounds."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.api.schemas import OrbitPropagationRequest
from orbitmind.core.config import Settings
from orbitmind.core.errors import ValidationError
from orbitmind.mission.models import MissionRequest, OutputType
from orbitmind.mission.validation import validate_mission_request

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 17, 0, 0, tzinfo=UTC)


def _request(**overrides: object) -> MissionRequest:
    base: dict[str, object] = {
        "satellite_id": "ISS",
        "start_time": START,
        "end_time": START + dt.timedelta(hours=1),
        "step_seconds": 60,
        "output_types": list(OutputType),
    }
    base.update(overrides)
    return MissionRequest(**base)  # type: ignore[arg-type]


def test_end_before_start_is_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        _request(end_time=START - dt.timedelta(minutes=1))


def test_naive_datetime_rejected_at_wire_layer() -> None:
    with pytest.raises(PydanticValidationError):
        OrbitPropagationRequest(
            satellite_id="ISS",
            start_time=dt.datetime(2019, 12, 9, 17, 0, 0),  # naive
            end_time=dt.datetime(2019, 12, 9, 18, 0, 0),
            step_seconds=60,
        )


def test_latitude_out_of_range_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        OrbitPropagationRequest(
            satellite_id="ISS",
            start_time=START,
            end_time=START + dt.timedelta(hours=1),
            step_seconds=60,
            observer_latitude=91.0,
        )


def test_unsupported_satellite_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported satellite"):
        validate_mission_request(_request(satellite_id="NOPE"), Settings(), {"ISS"})


def test_duration_over_limit_rejected() -> None:
    settings = Settings(max_propagation_hours=1.0)
    req = _request(end_time=START + dt.timedelta(hours=2))
    with pytest.raises(ValidationError, match="duration"):
        validate_mission_request(req, settings, {"ISS"})


def test_step_below_minimum_rejected() -> None:
    settings = Settings(min_step_seconds=30)
    with pytest.raises(ValidationError, match="step_seconds below"):
        validate_mission_request(_request(step_seconds=5), settings, {"ISS"})


def test_step_above_maximum_rejected() -> None:
    settings = Settings(max_step_seconds=600)
    with pytest.raises(ValidationError, match="step_seconds above"):
        validate_mission_request(_request(step_seconds=1200), settings, {"ISS"})


def test_too_many_samples_rejected() -> None:
    settings = Settings(max_samples=10)
    req = _request(end_time=START + dt.timedelta(hours=1), step_seconds=60)  # 61 samples
    with pytest.raises(ValidationError, match="sample count"):
        validate_mission_request(req, settings, {"ISS"})


def test_valid_request_passes() -> None:
    validate_mission_request(_request(), Settings(), {"ISS"})


def test_expected_sample_count() -> None:
    req = _request(end_time=START + dt.timedelta(hours=1), step_seconds=60)
    assert req.expected_sample_count() == 61
