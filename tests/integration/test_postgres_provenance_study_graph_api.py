"""Live PostgreSQL API tests for provenance study graph projections."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.core.checksums import sha256_text
from orbitmind.core.config import Settings
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.provenance_execution import (
    ProvenanceAnchoredPlanningExecution,
    execute_provenance_anchored_planning,
)
from orbitmind.persistence.observation_geometry_models import ObservationGeometryRunRow
from orbitmind.sources.registry import SourceRegistry

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

BASE = "/api/v1/provenance-graphs"
ROUTE = f"{BASE}/observation-study/geometry-planning-chain"
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=dt.UTC)
_TABLES = (
    "observation_planning_provenance_links",
    "observation_eligibility_windows",
    "observation_eligibility_window_sets",
    "observation_input_provenance_parents",
    "observation_input_provenance",
    "observation_geometry_runs",
    "observation_geometry_requests",
    "observation_plans",
    "observation_planning_runs",
    "observation_planning_requests",
)
_GRAPH_ERROR_FIELDS = (
    "graph_id",
    "scope_handle",
    "nodes",
    "edges",
    "node_count",
    "edge_count",
    "integrity_summary",
)
_EXPECTED_PROOF_SOURCES = {
    "recorded-provenance:derived-from-geometry",
    "recorded-fk:eligibility-set-to-provenance",
    "recorded-link:provenance-link-to-eligibility-provenance",
    "recorded-link:provenance-link-to-eligibility-set",
    "recorded-link:provenance-link-to-planning-request",
    "recorded-link:provenance-link-to-planning-run",
    "recorded-fk:planning-run-to-observation-plan",
    "recorded-summary:chain-integrity",
}


@pytest.fixture
def pg_container(tmp_path: Path) -> AppContainer:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield container
    container.database.engine.dispose()


def _client(
    container: AppContainer,
    owner_id: str = "owner-a",
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(site_id: str) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} PostgreSQL provenance graph API site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _persist_chain(
    container: AppContainer,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-PG-GRAPH-API",
) -> tuple[str, ProvenanceAnchoredPlanningExecution]:
    with container.database.session() as session:
        geometry_execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=_geometry_request(site_id),
            idempotency_key=f"pg-graph-api-geometry:{owner_id}:{site_id}",
        )
    with container.database.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id=owner_id,
            geometry_run_id=geometry_execution.run_id,
            requested_by="pg-graph-api-analyst",
        )
    with container.database.session() as session:
        execution = execute_provenance_anchored_planning(
            session=session,
            owner_id=owner_id,
            eligibility_set_id=derived.eligibility_set_record_id,
            requested_by="pg-graph-api-planner",
        )
    return geometry_execution.run_id, execution


def _params(
    geometry_run_id: str,
    execution: ProvenanceAnchoredPlanningExecution,
) -> dict[str, str]:
    return {
        "geometry_run_id": geometry_run_id,
        "provenance_link_id": execution.link_record_id,
    }


def _scope_handle(geometry_run_id: str, execution: ProvenanceAnchoredPlanningExecution) -> str:
    return f"observation-study-chain:{geometry_run_id}:{execution.link_record_id}"


def _normalize_read_at(body: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(body)
    normalized["read_at"] = "<read-at>"
    return normalized


def _assert_safe_error(response: Any) -> None:
    assert set(response.json()) == {"code", "message"}
    for forbidden in (
        *_GRAPH_ERROR_FIELDS,
        "SELECT",
        "uq_",
        "postgresql://",
        "Traceback",
        "result_json",
        "request_json",
        "link_json",
        "tle_line",
        "owner-a",
        "owner-b",
    ):
        assert forbidden not in response.text


def test_postgres_provenance_study_graph_api_success_owner_isolation_and_tamper(
    pg_container: AppContainer,
) -> None:
    run_id, execution = _persist_chain(pg_container, site_id="SITE-PG-GRAPH-A")
    other_run_id, _other_execution = _persist_chain(
        pg_container,
        site_id="SITE-PG-GRAPH-B",
    )
    owner_b_run_id, _owner_b_execution = _persist_chain(
        pg_container,
        owner_id="owner-b",
        site_id="SITE-PG-GRAPH-C",
    )

    with _client(pg_container, "owner-a") as owner_a:
        first = owner_a.get(ROUTE, params=_params(run_id, execution))
        second = owner_a.get(ROUTE, params=_params(run_id, execution))
        mismatch = owner_a.get(ROUTE, params=_params(other_run_id, execution))
        rejected_query = owner_a.get(ROUTE, params={**_params(run_id, execution), "owner_id": "x"})
        invalid_id = owner_a.get(
            ROUTE,
            params={
                "geometry_run_id": f" {run_id}",
                "provenance_link_id": execution.link_record_id,
            },
        )
    with _client(pg_container, "owner-b") as owner_b:
        hidden_geometry = owner_b.get(ROUTE, params=_params(run_id, execution))
        hidden_link = owner_b.get(ROUTE, params=_params(owner_b_run_id, execution))

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    scope_handle = _scope_handle(run_id, execution)
    assert body["schema_version"] == "provenance-graph-v1"
    assert body["scope_handle"] == scope_handle
    assert body["owner_scope"] == "trusted-owner-dependency"
    assert body["status"] == "chain-checks-consistent"
    assert body["node_count"] == len(body["nodes"])
    assert body["edge_count"] == len(body["edges"])
    assert body["nodes"][-1]["node_id"] == f"study-graph-node:integrity-summary:{scope_handle}"
    assert {edge["proof_source"] for edge in body["edges"]} == _EXPECTED_PROOF_SOURCES
    assert _normalize_read_at(body) == _normalize_read_at(second.json())
    for forbidden in ("result_json", "request_json", "link_json", "tle_line", "owner-a"):
        assert forbidden not in first.text

    assert mismatch.status_code == 422
    assert rejected_query.status_code == 422
    assert invalid_id.status_code == 422
    assert hidden_geometry.status_code == 404
    assert hidden_link.status_code == 404
    for response in (mismatch, rejected_query, invalid_id, hidden_geometry, hidden_link):
        assert run_id not in response.text
        assert execution.link_record_id not in response.text
        assert execution.link_checksum not in response.text
        assert scope_handle not in response.text
        _assert_safe_error(response)

    with pg_container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("pg-graph-api-tampered-geometry")
        session.commit()

    with _client(pg_container, "owner-a", raise_server_exceptions=False) as owner_a:
        tampered = owner_a.get(ROUTE, params=_params(run_id, execution))

    assert tampered.status_code == 422
    assert tampered.json()["code"] == "validation_error"
    assert scope_handle not in tampered.text
    _assert_safe_error(tampered)
