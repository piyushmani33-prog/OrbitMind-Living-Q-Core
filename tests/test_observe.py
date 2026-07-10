"""Tests for the bounded bundled-fixture OrbitMind Observe surface."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.routers import review
from orbitmind.core.config import Settings


def _observe_payload(**overrides: str) -> dict[str, str]:
    return {
        "satellite_identifier": "ISS (ZARYA)",
        "observer_latitude": "0",
        "observer_longitude": "0",
        "observer_altitude_m": "0",
        "time_window_hours": "1",
        **overrides,
    }


def test_observe_page_contains_bounded_offline_observer_form(client: TestClient) -> None:
    response = client.get("/observe")

    assert response.status_code == 200
    body = response.text
    assert "OrbitMind Observe" in body
    assert "Satellite name or NORAD ID" in body
    assert 'name="satellite_identifier"' in body
    assert 'name="observer_latitude"' in body
    assert 'name="observer_longitude"' in body
    assert 'name="observer_altitude_m"' in body
    assert 'name="time_window_hours"' in body
    assert "not live certified tracking" in body
    assert "not collision warning" in body
    assert "no maneuver recommendation" in body
    assert "orbital data freshness and uncertainty are shown" in body
    assert "no provider fetch" in body
    assert "no CelesTrak fetch" in body
    assert "anchored to the selected fixture TLE epoch" in body


@pytest.mark.parametrize("satellite_identifier", ("ISS (ZARYA)", "25544"))
def test_observe_run_returns_bounded_observation_report(
    client: TestClient,
    settings: Settings,
    satellite_identifier: str,
) -> None:
    response = client.post(
        "/observe/run",
        data=_observe_payload(satellite_identifier=satellite_identifier),
    )

    assert response.status_code == 200
    body = response.text
    assert "OrbitMind Observe Result" in body
    assert "ISS (ZARYA)" in body
    assert "NORAD ID" in body
    assert "source used</dt><dd>bundled offline catalog fixture" in body
    assert "source timestamp</dt><dd>fixture epoch; no fetched_at for bundled data" in body
    assert "TLE epoch" in body
    assert "data age" in body
    assert "propagation model</dt><dd>SGP4" in body
    assert "Observer and model" in body
    assert "Next sampled pass windows" in body
    assert "Rise azimuth" in body
    assert "Max elevation" in body
    assert "ground_track.png" in body
    assert "altitude_vs_time.png" in body
    assert "static_report.md" in body
    assert "static_report.json" in body
    assert "TLE/SGP4 can have kilometre-scale uncertainty" in body
    assert "No covariance is available." in body
    assert "No probability of collision is computed." in body
    assert "Not live certified tracking" in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_observe_uses_a_deterministic_fixture_epoch_checksum(client: TestClient) -> None:
    first = client.post("/observe/run", data=_observe_payload())
    second = client.post("/observe/run", data=_observe_payload())

    assert first.status_code == 200
    assert second.status_code == 200
    first_checksum = _observation_input_checksum(first.text)
    second_checksum = _observation_input_checksum(second.text)
    assert first_checksum == second_checksum


@pytest.mark.parametrize(
    ("payload_update", "expected"),
    [
        ({"observer_latitude": "91"}, "observer latitude must be between -90 and 90"),
        ({"observer_longitude": "-181"}, "observer longitude must be between -180 and 180"),
        ({"time_window_hours": "25"}, "time window must not exceed 24 hours"),
    ],
)
def test_observe_rejects_invalid_location_or_time_window_safely(
    client: TestClient,
    settings: Settings,
    payload_update: dict[str, str],
    expected: str,
) -> None:
    response = client.post("/observe/run", data=_observe_payload(**payload_update))

    assert response.status_code == 422
    body = response.text
    assert "OrbitMind Observe Error" in body
    assert expected in body
    assert "Traceback" not in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_observe_unknown_satellite_is_rejected_without_running_mission(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unknown satellite must not run a mission")

    monkeypatch.setattr(review, "run_bundled_observation", fail_run)

    response = client.post("/observe/run", data=_observe_payload(satellite_identifier="unknown"))

    assert response.status_code == 422
    body = response.text
    assert "bundled offline satellite was not found" in body
    assert "completed" not in body
    assert "Traceback" not in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_observe_rejects_large_request_and_markup_identifier_safely(
    client: TestClient,
    settings: Settings,
) -> None:
    large = client.post(
        "/observe/run",
        data=_observe_payload(satellite_identifier="x" * 1_025),
    )
    assert large.status_code == 422
    assert "observe request body is too large" in large.text
    assert "Traceback" not in large.text

    markup = client.post(
        "/observe/run",
        data=_observe_payload(satellite_identifier="<script>alert(1)</script>"),
    )
    assert markup.status_code == 422
    assert "unsupported markup characters" in markup.text
    assert "<script>" not in markup.text
    assert "alert(1)" not in markup.text
    assert "Traceback" not in markup.text
    assert str(settings.resolved_artifacts_dir()) not in markup.text


def _observation_input_checksum(body: str) -> str:
    match = re.search(
        r"<dt>observation input checksum</dt>\s*<dd><code>([0-9a-f]{64})</code></dd>",
        body,
    )
    assert match is not None
    return match.group(1)
