"""Integration tests for the mission API (submit, retrieve, list, artifacts)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ENDPOINT = "/api/v1/missions/orbit-propagation"


def test_submit_returns_typed_result_with_provenance(
    client: TestClient, iss_request: dict[str, object]
) -> None:
    response = client.post(ENDPOINT, json=iss_request)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "completed"
    assert body["epistemic_status"] == "deterministic-calculation"
    assert body["sample_count"] == 31
    assert len(body["artifacts"]) == 2
    assert body["disclaimer"]
    assert body["source"]["test_only"] is True
    assert body["provenance"][0]["method"] == "sgp4-propagation"
    assert body["provenance"][0]["inputs_hash"]


def test_retrieve_and_list(client: TestClient, iss_request: dict[str, object]) -> None:
    mission_id = client.post(ENDPOINT, json=iss_request).json()["mission_id"]

    retrieved = client.get(f"/api/v1/missions/{mission_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["mission_id"] == mission_id

    listing = client.get("/api/v1/missions").json()
    assert listing["total"] >= 1
    assert any(item["mission_id"] == mission_id for item in listing["items"])


def test_artifacts_endpoint(client: TestClient, iss_request: dict[str, object]) -> None:
    mission_id = client.post(ENDPOINT, json=iss_request).json()["mission_id"]
    artifacts = client.get(f"/api/v1/missions/{mission_id}/artifacts").json()
    assert artifacts["mission_id"] == mission_id
    types = {a["type"] for a in artifacts["artifacts"]}
    assert types == {"altitude_vs_time", "ground_track"}


def test_unknown_mission_returns_404(client: TestClient) -> None:
    response = client.get("/api/v1/missions/11111111-2222-3333-4444-555555555555")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_invalid_mission_id_returns_422(client: TestClient) -> None:
    response = client.get("/api/v1/missions/not-a-uuid")
    assert response.status_code == 422


def test_unsupported_satellite_returns_safe_422(
    client: TestClient, iss_request: dict[str, object]
) -> None:
    bad = {**iss_request, "satellite_id": "DOES_NOT_EXIST"}
    response = client.post(ENDPOINT, json=bad)
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    # Safe message: no stack trace / internal path.
    assert "Traceback" not in body["message"]


def test_end_before_start_returns_422(client: TestClient, iss_request: dict[str, object]) -> None:
    bad = {**iss_request, "end_time": "2019-12-09T16:00:00Z"}
    assert client.post(ENDPOINT, json=bad).status_code == 422
