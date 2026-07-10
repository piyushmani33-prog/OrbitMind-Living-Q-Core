"""Integration tests: missions using CelesTrak data (mocked HTTP) via the API."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.conftest import build_celestrak_omm, make_transport

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings

pytestmark = pytest.mark.integration

ENDPOINT = "/api/v1/missions/orbit-propagation"
ClientFactory = Callable[[httpx.MockTransport], TestClient]

_CELESTRAK_BODY = {
    "satellite_id": "25544",
    "source": "celestrak",
    "start_time": "2026-06-19T12:00:00Z",
    "end_time": "2026-06-19T12:30:00Z",
    "step_seconds": 300,
}


def test_celestrak_mission_success(celestrak_client_factory: ClientFactory) -> None:
    transport = make_transport(records=[build_celestrak_omm()])
    with celestrak_client_factory(transport) as client:
        response = client.post(ENDPOINT, json=_CELESTRAK_BODY)
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["sample_count"] == 7
        sd = body["source_data"]
        assert sd["source_id"] == "celestrak"
        assert sd["record_identifier"] == "25544"
        assert sd["liveness"] == "live"
        assert sd["freshness_state"] in {"current", "fresh"}
        assert "review" in sd["limitations"]
        # Provenance reaches the result and references the external source.
        prov = body["provenance"][0]
        assert prov["method"] == "sgp4-propagation"
        assert any(e["kind"] == "celestrak-gp" for e in prov["evidence"])
        actions = [a["action"] for a in body["audit"]]
        assert "source.record_normalized" in actions
        assert "mission.external_completed" in actions


def test_sample_mission_still_offline(celestrak_client_factory: ClientFactory) -> None:
    # A transport that would error if used — the sample path must not touch it.
    with celestrak_client_factory(make_transport(exc=httpx.ConnectTimeout)) as client:
        body = {
            "satellite_id": "ISS",
            "start_time": "2019-12-09T17:00:00Z",
            "end_time": "2019-12-09T17:30:00Z",
            "step_seconds": 300,
        }
        result = client.post(ENDPOINT, json=body).json()
        assert result["status"] == "completed"
        assert result["source_data"]["source_id"] == "sample"
        assert result["source_data"]["freshness_state"] == "test-fixture"


def _container(tmp_path: Path, *, network: bool, transport: httpx.MockTransport) -> AppContainer:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'm.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        network_enabled=network,
        celestrak_enabled=True,
        env="test",
    )
    return AppContainer(settings, celestrak_transport=transport, celestrak_sleep=lambda _: None)


def test_network_disabled_fails_with_no_silent_fallback(tmp_path: Path) -> None:
    container = _container(
        tmp_path, network=False, transport=make_transport(records=[build_celestrak_omm()])
    )
    with TestClient(create_app(container)) as client:
        response = client.post(ENDPOINT, json=_CELESTRAK_BODY)
        assert response.status_code == 409
        assert response.json()["code"] == "network_disabled"
        listing = client.get("/api/v1/missions").json()
        assert listing["total"] == 1
        assert listing["items"][0]["status"] == "failed"  # NOT silently completed via sample


def test_source_failure_no_silent_fallback(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[], status_code=503)) as client:
        response = client.post(ENDPOINT, json=_CELESTRAK_BODY)
        assert response.status_code == 503
        assert client.get("/api/v1/missions").json()["items"][0]["status"] == "failed"


def test_empty_provider_result_is_not_silently_replaced_with_sample(
    celestrak_client_factory: ClientFactory,
) -> None:
    with celestrak_client_factory(make_transport(records=[])) as client:
        response = client.post(ENDPOINT, json=_CELESTRAK_BODY)
        assert response.status_code == 404
        assert response.json()["code"] == "object_not_found"
        mission = client.get("/api/v1/missions").json()["items"][0]
        assert mission["status"] == "failed"


def test_mismatched_provider_identity_persists_no_source_data(
    celestrak_client_factory: ClientFactory,
) -> None:
    record = build_celestrak_omm()
    record["NORAD_CAT_ID"] = 12345
    with celestrak_client_factory(make_transport(records=[record])) as client:
        response = client.post(ENDPOINT, json=_CELESTRAK_BODY)
        assert response.status_code == 502
        assert response.json()["code"] == "source_schema_error"
        mission = client.get("/api/v1/missions").json()["items"][0]
        detail = client.get(f"/api/v1/missions/{mission['mission_id']}").json()
        assert detail["status"] == "failed"
        assert detail["source_data"] is None


def test_explicit_sample_fallback_is_unambiguous(
    celestrak_client_factory: ClientFactory,
) -> None:
    # CelesTrak fails, but the caller opted in to fallback and the id maps to a sample.
    with celestrak_client_factory(make_transport(records=[], status_code=503)) as client:
        body = {
            "satellite_id": "25544",
            "source": "celestrak",
            "allow_sample_fallback": True,
            "start_time": "2019-12-09T17:00:00Z",
            "end_time": "2019-12-09T17:30:00Z",
            "step_seconds": 300,
        }
        result = client.post(ENDPOINT, json=body).json()
        assert result["status"] == "completed"
        # Fallback is explicit and labelled: the source is sample, freshness is fixture.
        assert result["source_data"]["source_id"] == "sample"
        assert result["source_data"]["freshness_state"] == "test-fixture"
        assert "source.request_failed" in [a["action"] for a in result["audit"]]
