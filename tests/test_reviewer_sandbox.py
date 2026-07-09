"""Tests for the private browser reviewer sandbox."""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from orbitmind.core.config import Settings


def test_review_home_page_contains_bounded_sandbox_copy(client: TestClient) -> None:
    response = client.get("/review")

    assert response.status_code == 200
    body = response.text
    assert "OrbitMind Reviewer Sandbox" in body
    assert "Run bundled ISS sample" in body
    assert "available sample id" in body.lower()
    assert "iss" in body
    assert "not live tracking" in body
    assert "not production/public-alpha workflow" in body
    assert "no provider fetch" in body
    assert "no quantum advantage claim" in body


def test_review_run_returns_evidence_bundle_and_safety_boundary(
    client: TestClient,
    settings: Settings,
) -> None:
    response = client.post("/review/run")

    assert response.status_code == 200
    body = response.text
    assert "OrbitMind Reviewer Sandbox Result" in body
    assert "mission_id" in body
    assert "status</dt><dd>completed" in body
    assert "deterministic-calculation" in body
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
    assert "static_report.json" in body
    assert "static_report.md" in body
    assert "no quantum advantage claim" in body
    assert "not live tracking" in body
    assert str(settings.resolved_artifacts_dir()) not in body


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
