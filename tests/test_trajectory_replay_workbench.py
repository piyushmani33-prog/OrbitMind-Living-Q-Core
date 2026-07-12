"""Workbench route coverage for the offline animated trajectory replay surface."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from importlib import resources
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from orbitmind.api.app import WORKBENCH_REFERRER_POLICY
from orbitmind.api.container import AppContainer
from orbitmind.api.presentation.trajectory_replay import script_safe_json
from orbitmind.api.routers import workbench
from orbitmind.persistence.database import Base
from orbitmind.sources.registry import SourceRegistry
from orbitmind.trajectory_replay.models import TrajectoryReplayRequest, TrajectoryReplayResult
from orbitmind.trajectory_replay.service import TrajectoryReplayService


def _iss_tle() -> tuple[str, str]:
    return SourceRegistry().get_tle("ISS")


def _catalog_form(**updates: str) -> dict[str, str]:
    form = {
        "source_mode": "catalog",
        "catalog_sample_id": "iss",
        "custom_label": "",
        "tle_line1": "",
        "tle_line2": "",
        "observer_latitude_deg": "0",
        "observer_longitude_deg": "0",
        "observer_altitude_metres": "0",
        "start_time_utc": "2019-12-09T17:00:00Z",
        "duration_hours": "1",
        "minimum_elevation_deg": "0",
    }
    form.update(updates)
    return form


def _custom_form(**updates: str) -> dict[str, str]:
    line1, line2 = _iss_tle()
    form = _catalog_form(
        source_mode="custom",
        catalog_sample_id="",
        custom_label="Review ISS",
        tle_line1=line1,
        tle_line2=line2,
    )
    form.update(updates)
    return form


def _payload(body: str) -> dict[str, Any]:
    match = re.search(
        r'<template id="trajectory-replay-data">(.*?)</template>',
        body,
        re.S,
    )
    assert match is not None
    return json.loads(html.unescape(match.group(1)))


def _controller_script(client: TestClient) -> str:
    response = client.get("/assets/trajectory-replay.js")
    assert response.status_code == 200
    return response.text


def _handoff_form(body: str) -> dict[str, str]:
    match = re.search(
        r'<form method="post" action="/workbench/replay" class="action-row">(.*?)</form>',
        body,
        re.S,
    )
    assert match is not None
    return {
        name: html.unescape(value)
        for name, value in re.findall(
            r'<input type="hidden" name="([^"]+)"\s+value="([^"]*)">',
            match.group(1),
            re.S,
        )
    }


def _row_counts(container: AppContainer) -> dict[str, int]:
    names = sorted(Base.metadata.tables)
    with container.database.session() as session:
        return {
            name: int(session.execute(text(f"select count(*) from {name}")).scalar_one())
            for name in names
        }


def _artifact_files(container: AppContainer) -> set[Path]:
    root = container.settings.resolved_artifacts_dir()
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


def _cache_files(container: AppContainer) -> set[Path]:
    root = container.settings.resolved_cache_dir()
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


def test_workbench_get_contains_replay_action_and_existing_windows_action(
    client: TestClient,
) -> None:
    response = client.get("/workbench")

    assert response.status_code == 200
    body = response.text
    assert "Calculate Mission Windows" in body
    assert "Replay Predicted Trajectory" in body
    assert 'formaction="/workbench/replay"' in body
    assert "<script" not in body.lower()


def test_replay_is_server_rendered_html_and_no_json_api_is_added(client: TestClient) -> None:
    response = client.post("/workbench/replay", data=_catalog_form())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'none'; "
        "connect-src 'none'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'; "
        "form-action 'self'; "
        "worker-src 'none'; "
        "media-src 'none'; "
        "manifest-src 'none'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == WORKBENCH_REFERRER_POLICY
    assert "geolocation=()" in response.headers["permissions-policy"]
    assert client.get("/workbench/replay").status_code == 405


def test_replay_controller_asset_is_explicit_same_origin_and_packaged(
    client: TestClient,
) -> None:
    asset = client.get("/assets/trajectory-replay.js")
    missing = client.get("/assets/unknown.js")
    packaged = resources.files("orbitmind.api.assets").joinpath("trajectory_replay.js")

    assert asset.status_code == 200
    assert asset.headers["content-type"] == "application/javascript; charset=utf-8"
    assert asset.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in asset.headers
    assert "sourceMappingURL" not in asset.text
    assert "fetch" not in asset.text
    assert "XMLHttpRequest" not in asset.text
    assert "WebSocket" not in asset.text
    assert missing.status_code == 404
    assert packaged.is_file()
    assert packaged.read_text(encoding="utf-8") == asset.text


def test_replay_controller_asset_missing_fails_without_path_or_traceback(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_package(_package: str) -> object:
        raise FileNotFoundError("C:/private/assets/trajectory_replay.js")

    monkeypatch.setattr(workbench.resources, "files", missing_package)

    response = client.get("/assets/trajectory-replay.js")

    assert response.status_code == 500
    assert response.text == "Replay controller asset unavailable."
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "private" not in response.text
    assert "Traceback" not in response.text


def test_valid_offline_catalog_replay_renders_svg_payload_controls_and_evidence(
    client: TestClient,
) -> None:
    response = client.post("/workbench/replay", data=_catalog_form(duration_hours="6"))

    assert response.status_code == 200
    body = response.text
    payload = _payload(body)
    assert "Predicted trajectory replay; not live tracking." in body
    assert "Predicted from the identified orbital element set using the pinned propagation" in body
    assert "Offline orbital source" in body
    assert "Predicted trajectory" in body
    assert "Not live tracking" in body
    assert "<svg" in body
    assert '<title id="trajectory-title">Predicted trajectory ground track</title>' in body
    assert 'id="observer-marker"' in body
    assert 'id="satellite-marker"' in body
    assert "Play" in body
    assert 'id="replay-slider"' in body
    assert 'id="replay-speed"' in body
    assert 'aria-pressed="false"' in body
    assert "UTC timestamp" in body
    assert "Geodetic latitude" in body
    assert "Canonical longitude" in body
    assert "WGS84 altitude" in body
    assert "Azimuth" in body
    assert "Elevation" in body
    assert "Range" in body
    assert '<details class="section-gap">' in body
    assert "<summary>Method and evidence</summary>" in body
    assert "Input reference" in body
    assert "Result reference" in body
    assert "playback controls require local JavaScript" in body.replace("\n", " ")
    assert "prefers-reduced-motion" in _controller_script(client)
    assert '<template id="trajectory-replay-data">' in body
    assert '<script src="/assets/trajectory-replay.js" defer></script>' in body
    assert "<script>" not in body
    assert 'type="application/json"' not in body
    assert payload["schema_version"] == "trajectory-replay-display-v1"
    assert payload["sample_interval_seconds"] == 15
    assert payload["sample_count"] == len(payload["samples"])
    assert len(body.encode("utf-8")) < 1_000_000

    for control_id in (
        "replay-play",
        "replay-prev",
        "replay-slider",
        "replay-next",
        "replay-speed",
    ):
        assert re.search(rf'id="{control_id}"[^>]*\bdisabled\b', body)
    assert ".replay-controls :disabled" in body


def test_catalog_window_result_posts_exact_request_into_replay_without_persistence(
    client: TestClient,
    container: AppContainer,
) -> None:
    request_form = _catalog_form(
        observer_latitude_deg="12.9716",
        observer_longitude_deg="77.5946",
        observer_altitude_metres="920",
        start_time_utc="2019-12-09T17:00:00Z",
        duration_hours="6.25",
        minimum_elevation_deg="10",
    )
    before_rows = _row_counts(container)
    before_artifacts = _artifact_files(container)
    before_cache = _cache_files(container)

    window_response = client.post("/workbench/run", data=request_form)
    handoff = _handoff_form(window_response.text)
    replay_response = client.post("/workbench/replay", data=handoff)
    payload = _payload(replay_response.text)

    assert window_response.status_code == replay_response.status_code == 200
    assert window_response.headers["content-security-policy"]
    assert replay_response.headers["content-security-policy"]
    assert 'method="post" action="/workbench/replay"' in window_response.text
    assert "Replay this request" in window_response.text
    assert "This is not live tracking." in window_response.text
    assert "http://" not in window_response.text.lower()
    assert "https://" not in window_response.text.lower()
    assert handoff == request_form
    assert payload["source_identity"]["object_label"] == "ISS (ZARYA)"
    assert payload["source_identity"]["trajectory_reference"] == "offline-catalog:iss"
    assert payload["observer"]["latitude_deg"] == pytest.approx(12.9716)
    assert payload["observer"]["longitude_deg"] == pytest.approx(77.5946)
    assert payload["observer"]["altitude_km"] == pytest.approx(0.92)
    assert payload["samples"][0]["timestamp_utc"] == "2019-12-09T17:00:00.000Z"
    assert payload["samples"][-1]["timestamp_utc"] == "2019-12-09T23:15:00.000Z"
    assert payload["sample_interval_seconds"] == 30
    assert _row_counts(container) == before_rows
    assert _artifact_files(container) == before_artifacts
    assert _cache_files(container) == before_cache


def test_valid_custom_tle_replay_succeeds_without_rendering_raw_tle(client: TestClient) -> None:
    line1, line2 = _iss_tle()
    response = client.post(
        "/workbench/replay",
        data=_custom_form(custom_label="Alpha & Beta"),
    )

    assert response.status_code == 200
    body = response.text
    assert "Alpha &amp; Beta" in body
    assert "User-provided offline TLE" in body
    assert line1 not in body
    assert line2 not in body
    assert line1 not in json.dumps(_payload(body))
    assert line2 not in json.dumps(_payload(body))


def test_custom_tle_window_result_does_not_fake_or_leak_a_replay_handoff(
    client: TestClient,
) -> None:
    line1, line2 = _iss_tle()

    response = client.post("/workbench/run", data=_custom_form(custom_label="Alpha & Beta"))
    normalized = " ".join(response.text.split())

    assert response.status_code == 200
    assert "Direct replay handoff is unavailable for a request-local custom TLE" in normalized
    assert "No catalog object has been substituted." in normalized
    assert 'form method="post" action="/workbench/replay"' not in response.text
    assert "offline-catalog:iss" not in response.text
    assert line1 not in response.text
    assert line2 not in response.text
    assert "http://" not in response.text.lower()
    assert "https://" not in response.text.lower()


def test_replay_preserves_exactly_one_source_validation(client: TestClient) -> None:
    line1, line2 = _iss_tle()
    response = client.post(
        "/workbench/replay",
        data=_catalog_form(tle_line1=line1, tle_line2=line2),
    )

    assert response.status_code == 422
    assert "Choose exactly one offline source mode" in response.text
    assert line1 not in response.text


def test_replay_unknown_catalog_and_malformed_tle_fail_without_fallback(
    client: TestClient,
) -> None:
    unknown = client.post("/workbench/replay", data=_catalog_form(catalog_sample_id="unknown"))
    malformed = client.post(
        "/workbench/replay",
        data=_custom_form(tle_line1="not a TLE", tle_line2="not a TLE either"),
    )

    assert unknown.status_code == 422
    assert malformed.status_code == 422
    assert "ISS (ZARYA)" not in malformed.text
    assert "not a TLE" not in malformed.text
    assert _iss_tle()[0] not in malformed.text
    assert "Traceback" not in unknown.text + malformed.text


def test_replay_uses_trajectory_replay_service(
    client: TestClient,
    container: AppContainer,
) -> None:
    class SpyReplayService:
        def __init__(self) -> None:
            self.calls = 0
            self.real = TrajectoryReplayService()

        def calculate(self, request: TrajectoryReplayRequest) -> TrajectoryReplayResult:
            self.calls += 1
            return self.real.calculate(request)

    spy = SpyReplayService()
    container.trajectory_replay_service = spy  # type: ignore[assignment]

    response = client.post("/workbench/replay", data=_catalog_form())

    assert response.status_code == 200
    assert spy.calls == 1


def test_replay_rendering_helper_failure_returns_sanitized_error(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    line1, line2 = _iss_tle()

    def fail_render(*_args: object, **_kwargs: object) -> str:
        raise ValueError("internal renderer exploded with raw details")

    monkeypatch.setattr(workbench, "_replay_page", fail_render)

    response = client.post("/workbench/replay", data=_custom_form())

    assert response.status_code == 422
    body = response.text
    assert "The trajectory replay calculation could not complete safely." in body
    assert "Traceback" not in body
    assert "internal renderer exploded" not in body
    assert line1 not in body
    assert line2 not in body
    assert "trajectory-replay-data" not in body
    assert "Predicted trajectory" not in body
    assert "Offline orbital source" not in body
    assert "Not live tracking" not in body
    assert "<svg" not in body
    assert 'id="satellite-marker"' not in body


def test_mission_window_service_behavior_still_uses_existing_route(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(start_time_utc="2019-12-09T19:40:00Z"),
    )

    assert response.status_code == 200
    assert "Next predicted pass/contact window" in response.text
    assert "trajectory-replay-data" not in response.text


def test_replay_sample_step_policy(client: TestClient) -> None:
    cases: Mapping[str, int] = {
        "6": 15,
        "6.25": 30,
        "12": 30,
        "12.25": 60,
        "24": 60,
    }
    for duration, expected_step in cases.items():
        response = client.post(
            "/workbench/replay",
            data=_catalog_form(duration_hours=duration),
        )
        assert response.status_code == 200
        payload = _payload(response.text)
        assert payload["sample_interval_seconds"] == expected_step
        assert f"Selected sampling interval</dt><dd>{expected_step} seconds" in response.text
        assert payload["sample_count"] <= 1441


def test_track_segments_render_one_polyline_each_and_do_not_cross_world(
    client: TestClient,
) -> None:
    response = client.post(
        "/workbench/replay",
        data=_catalog_form(duration_hours="3", start_time_utc="2019-12-09T17:00:00Z"),
    )

    assert response.status_code == 200
    body = response.text
    payload = _payload(body)
    polyline_count = body.count('class="track-line"')
    assert polyline_count == len(payload["segments"])
    assert len(payload["segments"]) >= 2
    for points in re.findall(r'class="track-line" points="([^"]+)"', body):
        x_values = [float(point.split(",", maxsplit=1)[0]) for point in points.split()]
        for left, right in pairwise(x_values):
            assert abs(right - left) < 500.0
    flattened = [index for segment in payload["segments"] for index in segment]
    assert flattened == list(range(payload["sample_count"]))


def test_embedded_payload_is_script_safe_and_parseable() -> None:
    marker = "</script><script>alert(1)</script>"
    payload = script_safe_json(
        {
            "schema_version": "trajectory-replay-display-v1",
            "label": marker,
            "image": "<img src=x onerror=alert(1)>",
            "path": r"C:\private\secret.txt",
            "bearer": "Authorization: Bearer fake-secret",
        }
    )

    assert "</script>" not in payload.lower()
    assert "<img" not in payload.lower()
    assert "Authorization: Bearer" in json.loads(payload)["bearer"]


def test_replay_rejects_label_security_probes_without_reflection(client: TestClient) -> None:
    probes = (
        "</script><script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        r"C:\private\secret.txt",
        "/home/user/private.txt",
        "Authorization: Bearer fake-secret",
    )
    for probe in probes:
        response = client.post("/workbench/replay", data=_custom_form(custom_label=probe))
        assert response.status_code == 422
        assert probe not in response.text
        assert "Traceback" not in response.text
        assert _iss_tle()[0] not in response.text


def test_replay_html_and_controller_do_not_expose_forbidden_browser_behavior(
    client: TestClient,
) -> None:
    response = client.post("/workbench/replay", data=_catalog_form())

    assert response.status_code == 200
    body = response.text
    script = _controller_script(client)
    forbidden_script_tokens = (
        "eval",
        "new Function",
        "document.write",
        "innerHTML",
        "SGP4",
        "GMST",
        "TEME",
        "ECEF",
        "WGS84",
        "fetch",
        "XMLHttpRequest",
        "WebSocket",
    )
    for token in forbidden_script_tokens:
        assert token not in script
    assert "http://" not in body.lower()
    assert "https://" not in body.lower()
    assert "cdn" not in body.lower()
    assert "tile" not in body.lower()
    assert "real-time" not in body.lower()
    assert "100% accuracy" not in body.lower()
    assert "certified tracking" not in body.lower()
    assert r"C:\private\secret.txt" not in body
    assert "/home/user/private.txt" not in body
    assert "Authorization: Bearer" not in body


def test_replay_is_non_persistent_and_writes_no_artifacts(
    client: TestClient,
    container: AppContainer,
) -> None:
    before_counts = _row_counts(container)
    before_artifacts = _artifact_files(container)

    catalog = client.post("/workbench/replay", data=_catalog_form())
    custom = client.post("/workbench/replay", data=_custom_form())

    assert catalog.status_code == 200
    assert custom.status_code == 200
    assert _row_counts(container) == before_counts
    assert _artifact_files(container) == before_artifacts


def test_replay_route_preserves_existing_reviewer_and_artifact_surfaces(
    client: TestClient,
) -> None:
    assert client.get("/review").status_code == 200
    assert client.get("/review/artifacts/not-a-mission/unknown.txt").status_code in {
        400,
        404,
        422,
    }


def test_fixed_replay_request_has_stable_visible_values(client: TestClient) -> None:
    first = client.post("/workbench/replay", data=_catalog_form()).text
    second = client.post("/workbench/replay", data=_catalog_form()).text

    first_payload = _payload(first)
    second_payload = _payload(second)
    assert first_payload["samples"][0] == second_payload["samples"][0]
    assert first_payload["references"] == second_payload["references"]
    assert "2019-12-09 17:00:00.000 UTC" in first
