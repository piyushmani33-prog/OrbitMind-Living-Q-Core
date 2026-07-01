"""Live PostgreSQL API tests for read-only observation study chains."""

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

BASE = "/api/v1/observation-studies"
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
            name=f"{site_id} PostgreSQL observation study API site",
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
    site_id: str = "SITE-PG-STUDY-API",
) -> tuple[str, str, ProvenanceAnchoredPlanningExecution]:
    with container.database.session() as session:
        geometry_execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=_geometry_request(site_id),
            idempotency_key=f"pg-study-api-geometry:{owner_id}:{site_id}",
        )
    with container.database.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id=owner_id,
            geometry_run_id=geometry_execution.run_id,
            requested_by="pg-study-api-analyst",
        )
    with container.database.session() as session:
        execution = execute_provenance_anchored_planning(
            session=session,
            owner_id=owner_id,
            eligibility_set_id=derived.eligibility_set_record_id,
            requested_by="pg-study-api-planner",
        )
    return geometry_execution.run_id, geometry_execution.request_id, execution


def _params(
    geometry_run_id: str,
    execution: ProvenanceAnchoredPlanningExecution,
) -> dict[str, str]:
    return {
        "geometry_run_id": geometry_run_id,
        "provenance_link_id": execution.link_record_id,
    }


def _assert_safe_error(response: Any) -> None:
    assert set(response.json()) == {"code", "message"}
    for forbidden in (
        "SELECT",
        "uq_",
        "postgresql://",
        "Traceback",
        "result_json",
        "request_json",
        "link_json",
        "tle_line",
    ):
        assert forbidden not in response.text


def test_postgres_observation_study_api_success_owner_mismatch_and_tamper(
    pg_container: AppContainer,
) -> None:
    run_id, request_id, execution = _persist_chain(pg_container, site_id="SITE-PG-STUDY-API-A")
    other_run_id, _other_request_id, _other_execution = _persist_chain(
        pg_container,
        site_id="SITE-PG-STUDY-API-B",
    )
    owner_b_run_id, _owner_b_request_id, _owner_b_execution = _persist_chain(
        pg_container,
        owner_id="owner-b",
        site_id="SITE-PG-STUDY-API-C",
    )

    with _client(pg_container, "owner-a") as owner_a:
        success = owner_a.get(f"{BASE}/geometry-planning-chain", params=_params(run_id, execution))
        mismatch = owner_a.get(
            f"{BASE}/geometry-planning-chain",
            params=_params(other_run_id, execution),
        )
    with _client(pg_container, "owner-b") as owner_b:
        hidden_geometry = owner_b.get(
            f"{BASE}/geometry-planning-chain",
            params=_params(run_id, execution),
        )
        hidden_link = owner_b.get(
            f"{BASE}/geometry-planning-chain",
            params=_params(owner_b_run_id, execution),
        )

    assert success.status_code == 200
    body = success.json()
    assert body["owner_id"] == "owner-a"
    assert body["geometry"]["run_id"] == run_id
    assert body["geometry"]["request_id"] == request_id
    assert body["eligibility"]["source_type"] == "derived"
    assert body["eligibility"]["source_mode"] == "derived_from_geometry"
    assert body["eligibility"]["verification_status"] == "geometry_derived"
    assert body["planning"]["provenance_link_id"] == execution.link_record_id
    assert body["planning"]["planning_request_source_mode"] == "declared"
    assert "result_json" not in success.text
    assert "request_json" not in success.text
    assert "link_json" not in success.text
    assert "tle_line" not in success.text
    assert "does not prove live tracking" in body["disclaimer"]

    assert mismatch.status_code == 422
    assert hidden_geometry.status_code == 404
    assert hidden_link.status_code == 404
    for response in (mismatch, hidden_geometry, hidden_link):
        _assert_safe_error(response)

    with pg_container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("pg-api-study-tampered-geometry")
        session.commit()

    with _client(pg_container, "owner-a", raise_server_exceptions=False) as owner_a:
        tampered = owner_a.get(f"{BASE}/geometry-planning-chain", params=_params(run_id, execution))

    assert tampered.status_code == 422
    assert tampered.json()["code"] == "validation_error"
    _assert_safe_error(tampered)


def test_postgres_observation_study_integrity_summary_api_success_owner_mismatch_and_tamper(
    pg_container: AppContainer,
) -> None:
    run_id, _request_id, execution = _persist_chain(
        pg_container,
        site_id="SITE-PG-STUDY-INTEGRITY-A",
    )
    other_run_id, _other_request_id, _other_execution = _persist_chain(
        pg_container,
        site_id="SITE-PG-STUDY-INTEGRITY-B",
    )
    owner_b_run_id, _owner_b_request_id, _owner_b_execution = _persist_chain(
        pg_container,
        owner_id="owner-b",
        site_id="SITE-PG-STUDY-INTEGRITY-C",
    )
    route = f"{BASE}/geometry-planning-chain/integrity-summary"

    with _client(pg_container, "owner-a") as owner_a:
        success = owner_a.get(route, params=_params(run_id, execution))
        mismatch = owner_a.get(route, params=_params(other_run_id, execution))
    with _client(pg_container, "owner-b") as owner_b:
        hidden_geometry = owner_b.get(route, params=_params(run_id, execution))
        hidden_link = owner_b.get(route, params=_params(owner_b_run_id, execution))

    assert success.status_code == 200
    body = success.json()
    assert body["owner_id"] == "owner-a"
    assert body["geometry_run_id"] == run_id
    assert body["eligibility_set_id"] == execution.eligibility_set_record_id
    assert body["planning_request_id"] == execution.planning_request_id
    assert body["planning_run_id"] == execution.planning_run_id
    assert body["provenance_link_id"] == execution.link_record_id
    assert body["provenance_link_checksum"] == execution.link_checksum
    assert body["status"] == "chain-checks-consistent"
    assert body["overall_passed"] is True
    assert body["failed_check_count"] == 0
    assert all(check["passed"] for check in body["checks"])
    assert "checksum and stored-record consistency" in body["limitations"][-1]
    assert "does not prove live tracking" in body["disclaimer"]
    assert "result_json" not in success.text
    assert "request_json" not in success.text
    assert "link_json" not in success.text
    assert "tle_line" not in success.text

    assert mismatch.status_code == 422
    assert hidden_geometry.status_code == 404
    assert hidden_link.status_code == 404
    for response in (mismatch, hidden_geometry, hidden_link):
        assert "chain-checks-consistent" not in response.text
        _assert_safe_error(response)

    with pg_container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("pg-api-study-integrity-tampered-geometry")
        session.commit()

    with _client(pg_container, "owner-a", raise_server_exceptions=False) as owner_a:
        tampered = owner_a.get(route, params=_params(run_id, execution))

    assert tampered.status_code == 422
    assert tampered.json()["code"] == "validation_error"
    assert "chain-checks-consistent" not in tampered.text
    _assert_safe_error(tampered)
