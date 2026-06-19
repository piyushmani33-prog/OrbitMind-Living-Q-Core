"""Integration test for the full deterministic orbital workflow + audit trail."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration

ENDPOINT = "/api/v1/missions/orbit-propagation"


def test_full_workflow_records_audit_and_passes_verification(
    client: TestClient, iss_request: dict[str, object]
) -> None:
    body = client.post(ENDPOINT, json=iss_request).json()

    actions = [event["action"] for event in body["audit"]]
    for required in (
        "mission.submitted",
        "mission.validated",
        "workflow.started",
        "propagation.completed",
        "verification.completed",
        "mission.completed",
    ):
        assert required in actions
    assert actions.count("artifact.generated") == 2

    # Every verification check passed for the clean sample.
    assert body["findings"]
    assert all(f["status"] == "passed" for f in body["findings"])

    # Units are explicit and present (SR-02).
    assert body["units"]["altitude"].startswith("km")
    assert body["units"]["time"].startswith("UTC")

    # Samples carry deterministic numeric outputs.
    first = body["samples"][0]
    assert first["status"] == "ok"
    assert first["altitude_km"] is not None
    assert first["position_km"] is not None


def test_workflow_is_reproducible(client: TestClient, iss_request: dict[str, object]) -> None:
    a = client.post(ENDPOINT, json=iss_request).json()["samples"]
    b = client.post(ENDPOINT, json=iss_request).json()["samples"]
    assert [s["altitude_km"] for s in a] == [s["altitude_km"] for s in b]
    assert [s["longitude_deg"] for s in a] == [s["longitude_deg"] for s in b]
