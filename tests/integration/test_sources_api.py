"""Integration tests for the source API endpoints (mocked HTTP)."""

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

ClientFactory = Callable[[httpx.MockTransport], TestClient]


def test_list_and_describe_sources(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[build_celestrak_omm()])) as client:
        sources = client.get("/api/v1/sources").json()
        assert {s["source_id"] for s in sources} >= {"sample", "celestrak"}
        assert client.get("/api/v1/sources/celestrak").json()["network_enabled"] is True
        assert client.get("/api/v1/sources/unknown").status_code == 404


def test_policy_endpoint_exposes_no_paths(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[build_celestrak_omm()])) as client:
        policy = client.get("/api/v1/sources/celestrak/policy").json()
        assert policy["allowed_hostnames"] == ["celestrak.org"]
        assert policy["https_only"] is True
        assert policy["license"]["requires_review"] is True
        assert policy["license"]["commercial_use_confirmed"] is False


def test_health_endpoint_no_network(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[build_celestrak_omm()])) as client:
        health = client.get("/api/v1/sources/celestrak/health").json()
        assert health["source_id"] == "celestrak"
        assert health["health"] in {"healthy", "unknown", "degraded", "disabled"}


def test_refresh_then_cache_listing(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[build_celestrak_omm()])) as client:
        refreshed = client.post(
            "/api/v1/sources/celestrak/refresh", params={"satellite_id": "25544"}
        ).json()
        assert refreshed["outcome"] == "fetched"
        cache = client.get("/api/v1/sources/celestrak/cache").json()
        assert len(cache["entries"]) == 1
        # The internal filesystem path is never exposed.
        assert "body_path" not in cache["entries"][0]


def test_refresh_respects_min_interval(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[build_celestrak_omm()])) as client:
        first = client.post(
            "/api/v1/sources/celestrak/refresh", params={"satellite_id": "25544"}
        ).json()
        second = client.post(
            "/api/v1/sources/celestrak/refresh", params={"satellite_id": "25544"}
        ).json()
        assert first["outcome"] == "fetched"
        assert second["outcome"] == "suppressed"  # min-refresh interval enforced


def test_refresh_invalid_satellite_id_rejected(celestrak_client_factory: ClientFactory) -> None:
    with celestrak_client_factory(make_transport(records=[build_celestrak_omm()])) as client:
        response = client.post("/api/v1/sources/celestrak/refresh", params={"satellite_id": "ISS"})
        assert response.status_code == 422  # must be a NORAD number


def test_refresh_disabled_when_network_off(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 's.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        network_enabled=False,
        celestrak_enabled=True,
        env="test",
    )
    container = AppContainer(
        settings,
        celestrak_transport=make_transport(records=[build_celestrak_omm()]),
        celestrak_sleep=lambda _: None,
    )
    with TestClient(create_app(container)) as client:
        result = client.post(
            "/api/v1/sources/celestrak/refresh", params={"satellite_id": "25544"}
        ).json()
        assert result["outcome"] == "disabled"
