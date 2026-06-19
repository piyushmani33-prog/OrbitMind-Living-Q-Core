"""Integration tests for system endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["database"] == "connected"
    assert data["execution_mode"] == "local"
    assert data["quantum"] in ("available", "unavailable")
    assert data["python_version"]
    # No sensitive paths or env leaked.
    assert "database_url" not in data


def test_version(client: TestClient) -> None:
    data = client.get("/version").json()
    assert data["version"]
    assert "python" in data["components"]
    assert "sgp4" in data["components"]


def test_capabilities(client: TestClient) -> None:
    data = client.get("/api/v1/system/capabilities").json()
    names = {c["name"] for c in data}
    assert {"orbital-propagation", "verification", "visualization", "persistence"} <= names
