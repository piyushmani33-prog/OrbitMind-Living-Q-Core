"""Integration tests for the small-body + space-object API (mocked HTTP)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.conftest import load_jpl_fixture, make_jpl_transport

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings

pytestmark = pytest.mark.integration

ClientFactory = Callable[[httpx.MockTransport], TestClient]
LOOKUP = "/api/v1/small-bodies/lookup"


def _apophis_sbdb() -> dict[str, Any]:
    body = load_jpl_fixture("sbdb_asteroid.json")
    body["object"]["des"] = "99942"
    body["object"]["number"] = "99942"
    body["object"]["fullname"] = "99942 Apophis (2004 MN4)"
    body["object"]["shortname"] = "99942 Apophis"
    return body


def test_asteroid_lookup_and_persistence(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json"))
    with jpl_client_factory(transport) as client:
        resp = client.post(LOOKUP, json={"identifier": "433"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["record"]["identity"]["kind"] == "asteroid"
        assert body["record"]["epistemic_status"] == "deterministic-calculation"
        assert body["from_cache"] is False
        assert any(f["status"] == "passed" for f in body["findings"])
        assert "impact" in body["disclaimer"].lower()
        object_id = body["record"]["id"]

        # Persisted and retrievable via both space-objects and small-bodies.
        listing = client.get("/api/v1/space-objects").json()
        assert listing["total"] >= 1
        assert any(i["kind"] == "asteroid" for i in listing["items"])
        stored = client.get(f"/api/v1/small-bodies/{object_id}").json()
        assert stored["canonical_name"].startswith("433")
        assert stored["orbit"]["elements"]["semimajor_axis_au"] == 1.458
        # No internal cache path leaks into responses.
        assert "body_path" not in resp.text


def test_comet_lookup(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_comet.json"))
    with jpl_client_factory(transport) as client:
        body = client.post(LOOKUP, json={"identifier": "1P"}).json()
        assert body["record"]["identity"]["kind"] == "comet"


def test_cached_lookup(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json"))
    with jpl_client_factory(transport) as client:
        assert client.post(LOOKUP, json={"identifier": "433"}).json()["from_cache"] is False
        assert client.post(LOOKUP, json={"identifier": "433"}).json()["from_cache"] is True


def test_not_found_returns_404(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_not_found.json"))
    with jpl_client_factory(transport) as client:
        resp = client.post(LOOKUP, json={"identifier": "ZZZ"})
        assert resp.status_code == 404
        assert resp.json()["code"] == "object_not_found"


def test_malformed_returns_502(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_malformed.json"))
    with jpl_client_factory(transport) as client:
        assert client.post(LOOKUP, json={"identifier": "433"}).status_code == 502


def test_artifact_generation(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json"))
    with jpl_client_factory(transport) as client:
        body = client.post(LOOKUP, json={"identifier": "433", "generate_artifacts": True}).json()
        types = {a["type"] for a in body["artifacts"]}
        assert "orbit_parameter_summary" in types
        assert "keplerian_orbit_2d" in types  # asteroid 433 has a closed elliptical orbit


def test_constrained_query(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(query=load_jpl_fixture("query_response.json"))
    with jpl_client_factory(transport) as client:
        body = client.post(
            "/api/v1/small-bodies/query",
            json={"limit": 2, "output_fields": ["full_name", "neo", "a"], "sort_field": "a"},
        ).json()
        assert body["returned"] == 2
        assert body["truncated"] is True
        assert body["total_reported"] == 5


def test_close_approaches_and_join(jpl_client_factory: ClientFactory) -> None:
    transport = make_jpl_transport(sbdb=_apophis_sbdb(), cad=load_jpl_fixture("cad_response.json"))
    with jpl_client_factory(transport) as client:
        cad = client.post(
            "/api/v1/small-bodies/close-approaches",
            json={
                "filter": {"date_min": "2026-01-01T00:00:00Z", "date_max": "2026-12-01T00:00:00Z"}
            },
        ).json()
        assert cad["result"]["returned"] == 3
        assert "impact" in cad["disclaimer"].lower()
        # Lookup Apophis (des 99942) and join the stored close approaches by designation.
        obj = client.post(LOOKUP, json={"identifier": "99942"}).json()["record"]["id"]
        joined = client.get(f"/api/v1/small-bodies/{obj}/close-approaches").json()
        assert joined["designation"] == "99942"
        assert any(a["designation"] == "99942" for a in joined["approaches"])


def test_network_disabled_fails(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'n.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        network_enabled=False,
        jpl_sbdb_enabled=True,
        env="test",
    )
    container = AppContainer(
        settings,
        jpl_transport=make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json")),
        jpl_sleep=lambda _: None,
    )
    with TestClient(create_app(container)) as client:
        resp = client.post(LOOKUP, json={"identifier": "433"})
        assert resp.status_code == 409
        assert resp.json()["code"] == "network_disabled"
