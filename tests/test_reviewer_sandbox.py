"""Tests for the private browser reviewer sandbox."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.routers import review
from orbitmind.core.config import Settings

_ISS_TLE_LINE_1 = "1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991"
_ISS_TLE_LINE_2 = "2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482"


def test_review_home_page_contains_bounded_sandbox_copy(client: TestClient) -> None:
    response = client.get("/review")

    assert response.status_code == 200
    body = response.text
    assert "OrbitMind Reviewer Sandbox" in body
    assert "Evidence-backed offline orbital sample" in body
    assert "Run bundled ISS sample" in body
    assert "available sample id" in body.lower()
    assert "iss" in body
    assert "bundled stale sample/test-only data" in body
    assert "not live tracking" in body
    assert "not production/public-alpha workflow" in body
    assert "no provider fetch" in body
    assert "no quantum advantage claim" in body


def test_catalog_page_contains_bounded_fixture_metadata(client: TestClient) -> None:
    response = client.get("/review/catalog")

    assert response.status_code == 200
    body = response.text
    assert "Bundled Offline Satellite Catalog" in body
    assert "ISS (ZARYA)" in body
    assert "sample id" in body
    assert "NORAD catalog id" in body
    assert "25544" in body
    assert "orbit class" in body
    assert "LEO" in body
    assert "TLE epoch" in body
    assert "TLE age" in body
    assert "Generate evidence bundle" in body
    assert "not live tracking" in body
    assert "no covariance available" in body
    assert "no collision probability computed" in body
    assert "not production/public-alpha workflow" in body


def test_catalog_run_returns_evidence_bundle_and_accuracy_limitations(
    client: TestClient,
    settings: Settings,
) -> None:
    response = client.post("/review/catalog/run", data={"sample_id": "iss"})

    assert response.status_code == 200
    body = response.text
    assert "Bundled Offline Satellite Catalog Result" in body
    assert "Catalog selection" in body
    assert "ISS (ZARYA)" in body
    assert "mission_id" in body
    assert "completed" in body
    assert "deterministic-calculation" in body
    assert "ground_track.png" in body
    assert "altitude_vs_time.png" in body
    assert "static_report.md" in body
    assert "static_report.json" in body
    assert "Accuracy / limitations" in body
    assert "No covariance is available." in body
    assert "No collision probability is computed." in body
    assert "not live tracking" in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_catalog_unknown_sample_is_rejected_without_running_mission(
    client: TestClient,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run_sample(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unknown catalog sample must not run a mission")

    monkeypatch.setattr(review, "run_sample", fail_run_sample)

    response = client.post("/review/catalog/run", data={"sample_id": "unknown"})

    assert response.status_code == 422
    body = response.text
    assert "Bundled Offline Satellite Catalog Error" in body
    assert "selected bundled offline catalog sample is not available" in body
    assert "Traceback" not in body
    assert "completed" not in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_custom_tle_page_contains_bounded_offline_form(client: TestClient) -> None:
    response = client.get("/review/custom-tle")

    assert response.status_code == 200
    body = response.text
    assert "Offline Custom TLE Reviewer" in body
    assert "Paste a two-line element set" in body
    assert 'name="satellite_label"' in body
    assert 'name="tle_line1"' in body
    assert 'name="tle_line2"' in body
    assert "Generate offline evidence bundle" in body
    assert "user-provided offline TLE only" in body
    assert "not live tracking" in body
    assert "no CelesTrak fetch" in body
    assert "not production/public-alpha workflow" in body


def test_review_run_returns_evidence_bundle_and_safety_boundary(
    client: TestClient,
    settings: Settings,
) -> None:
    response = client.post("/review/run")

    assert response.status_code == 200
    body = response.text
    assert "OrbitMind Reviewer Sandbox Result" in body
    assert "Generated evidence bundle" in body
    assert "Mission summary" in body
    assert "Evidence / hashes" in body
    assert "Visual artifacts" in body
    assert "Reports" in body
    assert "Artifact checksum table" in body
    assert "mission_id" in body
    assert "completed" in body
    assert "deterministic-calculation" in body
    assert "test-only" in body
    assert "sample_count</dt><dd>31" in body
    assert "source.test_only</dt><dd>true" in body
    assert "source_checksum" in body
    assert "inputs_hash" in body
    assert "first_sample" in body
    assert "last_sample" in body
    assert "altitude_vs_time.png" in body
    assert "altitude_vs_time.json" in body
    assert "ground_track.png" in body
    assert "ground_track.json" in body
    assert '<img src="/review/artifacts/' in body
    assert "static_report.json" in body
    assert "static_report.md" in body
    assert "Safety boundary" in body
    assert "no quantum advantage claim" in body
    assert "not live tracking" in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_custom_tle_run_returns_evidence_bundle_and_safety_boundary(
    client: TestClient,
    settings: Settings,
) -> None:
    response = client.post(
        "/review/custom-tle/run",
        data={
            "satellite_label": "Reviewer ISS",
            "tle_line1": _ISS_TLE_LINE_1,
            "tle_line2": _ISS_TLE_LINE_2,
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "Offline Custom TLE Reviewer Result" in body
    assert "mission_id" in body
    assert "completed" in body
    assert "deterministic-calculation" in body
    assert "sample_count" in body
    assert "source label</dt><dd>user-provided offline TLE" in body
    assert "source name</dt><dd>Reviewer ISS" in body
    assert "source_checksum" in body
    assert "inputs_hash" in body
    assert "first_sample" in body
    assert "last_sample" in body
    assert "ground_track.png" in body
    assert "altitude_vs_time.png" in body
    assert "static_report.md" in body
    assert "static_report.json" in body
    assert "no provider fetch" in body
    assert "no CelesTrak fetch" in body
    assert "not live tracking" in body
    assert "no quantum advantage claim" in body
    assert str(settings.resolved_artifacts_dir()) not in body


@pytest.mark.parametrize(
    ("payload_update", "expected"),
    [
        ({"tle_line1": ""}, "TLE line 1 is required"),
        ({"tle_line2": ""}, "TLE line 2 is required"),
        ({"tle_line1": "9 25544U 98067A   19343.69339541"}, "TLE line 1 must start with"),
        ({"tle_line2": "9 25544  51.6439 211.2001"}, "TLE line 2 must start with"),
        ({"satellite_label": "x" * 81}, "satellite label must be 80 characters or fewer"),
    ],
)
def test_custom_tle_invalid_input_returns_safe_error(
    client: TestClient,
    settings: Settings,
    payload_update: dict[str, str],
    expected: str,
) -> None:
    payload = {
        "satellite_label": "Reviewer ISS",
        "tle_line1": _ISS_TLE_LINE_1,
        "tle_line2": _ISS_TLE_LINE_2,
        **payload_update,
    }

    response = client.post("/review/custom-tle/run", data=payload)

    assert response.status_code == 422
    body = response.text
    assert "Offline Custom TLE Reviewer Error" in body
    assert "Validation error" in body
    assert expected in body
    assert "Traceback" not in body
    assert str(settings.resolved_artifacts_dir()) not in body


def test_custom_tle_label_markup_is_rejected_without_rendering_html(
    client: TestClient,
) -> None:
    response = client.post(
        "/review/custom-tle/run",
        data={
            "satellite_label": "<script>alert(1)</script>",
            "tle_line1": _ISS_TLE_LINE_1,
            "tle_line2": _ISS_TLE_LINE_2,
        },
    )

    assert response.status_code == 422
    body = response.text
    assert "unsupported markup characters" in body
    assert "<script>" not in body
    assert "alert(1)" not in body
    assert "Traceback" not in body


def test_review_artifact_links_are_whitelisted(
    client: TestClient,
    settings: Settings,
) -> None:
    response = client.post("/review/run")
    assert response.status_code == 200
    mission_id = _extract_mission_id(response.text)

    allowed = client.get(f"/review/artifacts/{mission_id}/static_report.md")
    assert allowed.status_code == 200
    assert "OrbitMind Offline Sample Static Report" in allowed.text

    unknown = client.get(f"/review/artifacts/{mission_id}/unknown.txt")
    assert unknown.status_code == 404
    assert str(settings.resolved_artifacts_dir()) not in unknown.text

    traversal = client.get(f"/review/artifacts/{mission_id}/..%2Fstatic_report.md")
    assert traversal.status_code >= 400
    assert str(settings.resolved_artifacts_dir()) not in traversal.text


def _extract_mission_id(body: str) -> str:
    match = re.search(r"<dt>mission_id</dt><dd>([0-9a-f-]+)</dd>", body)
    assert match is not None
    return match.group(1)
