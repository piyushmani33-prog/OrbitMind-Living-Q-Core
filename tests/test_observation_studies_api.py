"""HTTP API tests for read-only observation study chains."""

from __future__ import annotations

import ast
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import orbitmind.api.routers.observation_studies as observation_studies_router
import orbitmind.observation_geometry.persistence_service as geometry_persistence_service
import orbitmind.observation_planning.orchestration as orchestration_module
from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.observation_studies_schemas import OBSERVATION_STUDY_DISCLAIMER
from orbitmind.core.checksums import sha256_text
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    GEOMETRY_DERIVED_ACCESS_LIMITATION,
    GEOMETRY_DERIVED_LIMITATION,
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.models import ObservationPlanningRequest
from orbitmind.observation_planning.provenance_execution import (
    ProvenanceAnchoredPlanningExecution,
    execute_provenance_anchored_planning,
)
from orbitmind.observation_studies import (
    OBSERVATION_STUDY_CHAIN_INTEGRITY_DISCLAIMER,
    OBSERVATION_STUDY_CHAIN_INTEGRITY_LIMITATION,
    OBSERVATION_STUDY_CHAIN_INTEGRITY_STATUS,
    ObservationStudyChain,
    get_geometry_planning_study_chain,
    summarize_geometry_planning_study_chain,
)
from orbitmind.persistence.observation_geometry_models import ObservationGeometryRunRow
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationInputProvenanceRow,
    ObservationPlanningProvenanceLinkRow,
    ObservationPlanningRunRow,
)
from orbitmind.sources.registry import SourceRegistry

BASE = "/api/v1/observation-studies"
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=dt.UTC)


@dataclass(frozen=True)
class StudyApiFixture:
    geometry_run_id: str
    geometry_request_id: str
    execution: ProvenanceAnchoredPlanningExecution


def _owner_client(
    container: AppContainer,
    owner_id: str,
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


def _geometry_request(site_id: str = "SITE-STUDY-API") -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} observation study API test site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _persist_study_chain(
    container: AppContainer,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-STUDY-API",
) -> StudyApiFixture:
    with container.database.session() as session:
        geometry_execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=_geometry_request(site_id),
            idempotency_key=f"study-api-geometry:{owner_id}:{site_id}",
        )
    with container.database.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id=owner_id,
            geometry_run_id=geometry_execution.run_id,
            requested_by="study-api-analyst",
        )
    with container.database.session() as session:
        execution = execute_provenance_anchored_planning(
            session=session,
            owner_id=owner_id,
            eligibility_set_id=derived.eligibility_set_record_id,
            requested_by="study-api-planner",
        )
    return StudyApiFixture(
        geometry_run_id=geometry_execution.run_id,
        geometry_request_id=geometry_execution.request_id,
        execution=execution,
    )


def _chain_params(fixture: StudyApiFixture) -> dict[str, str]:
    return {
        "geometry_run_id": fixture.geometry_run_id,
        "provenance_link_id": fixture.execution.link_record_id,
    }


def _assert_no_raw_study_text(text: str) -> None:
    lowered = text.lower()
    for forbidden in (
        '"result_json"',
        '"request_json"',
        '"link_json"',
        '"request_snapshot"',
        '"run_snapshot"',
        '"provenance_snapshot"',
        '"planning_snapshot"',
        '"tle_line1"',
        '"tle_line2"',
        '"samples"',
        '"intervals"',
        "select ",
        "insert ",
        "postgresql://",
        "sqlite",
        "traceback",
        "e:\\",
        ".py",
    ):
        assert forbidden not in lowered


def _assert_safe_error(response: Any) -> None:
    body = response.json()
    assert set(body) == {"code", "message"}
    _assert_no_raw_study_text(response.text)


def test_observation_study_api_returns_authenticated_safe_chain(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _persist_study_chain(container)

    def fail_geometry_compute(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise AssertionError("study API must not recompute geometry")

    def fail_planner(_: ObservationPlanningRequest) -> object:
        raise AssertionError("study API must not execute planning")

    monkeypatch.setattr(
        geometry_persistence_service,
        "compute_observation_geometry",
        fail_geometry_compute,
    )
    monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)

    with _owner_client(container, "owner-a") as client:
        response = client.get(f"{BASE}/geometry-planning-chain", params=_chain_params(fixture))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "schema_version",
        "owner_id",
        "geometry",
        "eligibility",
        "planning",
        "checks",
        "limitations",
        "disclaimer",
    }
    assert body["disclaimer"] == OBSERVATION_STUDY_DISCLAIMER
    assert "read-only authenticated traceability" in body["disclaimer"]
    assert "pinned/offline geometry-derived eligibility" in body["disclaimer"]
    for phrase in (
        "does not prove live tracking",
        "operational access",
        "taskability",
        "command readiness",
        "approval",
        "signed receipt status",
        "quantum authority",
    ):
        assert phrase in body["disclaimer"]

    assert body["owner_id"] == "owner-a"
    assert body["geometry"]["run_id"] == fixture.geometry_run_id
    assert body["geometry"]["request_id"] == fixture.geometry_request_id
    assert body["geometry"]["satellite_id"] == "ISS"
    assert body["geometry"]["site_id"] == "SITE-STUDY-API"
    assert body["geometry"]["sample_count"] > 0
    assert body["geometry"]["interval_count"] >= 0
    assert body["eligibility"]["source_type"] == "derived"
    assert body["eligibility"]["source_mode"] == "derived_from_geometry"
    assert body["eligibility"]["verification_status"] == "geometry_derived"
    assert body["eligibility"]["eligibility_set_id"] == fixture.execution.eligibility_set_record_id
    assert body["eligibility"]["selected_window_ids"] == list(fixture.execution.selected_window_ids)
    assert body["eligibility"]["selected_window_count"] == len(
        fixture.execution.selected_window_ids
    )
    assert body["planning"]["preparation_checksum"] == fixture.execution.preparation_checksum
    assert body["planning"]["planning_request_id"] == fixture.execution.planning_request_id
    assert body["planning"]["planning_run_id"] == fixture.execution.planning_run_id
    assert body["planning"]["observation_plan_id"] == fixture.execution.observation_plan_id
    assert body["planning"]["provenance_link_id"] == fixture.execution.link_record_id
    assert body["planning"]["link_checksum"] == fixture.execution.link_checksum
    assert body["planning"]["planning_request_source_mode"] == "declared"
    assert all(check["passed"] for check in body["checks"])
    assert {check["check_id"] for check in body["checks"]} == {
        "geometry-provenance-checksum",
        "geometry-source-identity",
        "eligibility-window-geometry",
        "planning-link-authenticated",
    }
    assert GEOMETRY_DERIVED_LIMITATION in body["limitations"]
    assert GEOMETRY_DERIVED_ACCESS_LIMITATION in body["limitations"]
    _assert_no_raw_study_text(response.text)


def test_observation_study_integrity_summary_api_returns_compact_success_summary(
    container: AppContainer,
) -> None:
    fixture = _persist_study_chain(container, site_id="SITE-STUDY-INTEGRITY-API")
    with container.database.session() as session:
        summary = summarize_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )

    with _owner_client(container, "owner-a") as client:
        response = client.get(
            f"{BASE}/geometry-planning-chain/integrity-summary",
            params=_chain_params(fixture),
        )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "owner_id",
        "geometry_run_id",
        "geometry_run_checksum",
        "source_identity_checksum",
        "eligibility_set_id",
        "eligibility_set_checksum",
        "planning_request_id",
        "planning_run_id",
        "observation_plan_id",
        "provenance_link_id",
        "provenance_link_checksum",
        "status",
        "overall_passed",
        "check_count",
        "failed_check_count",
        "checks",
        "limitations",
        "disclaimer",
    }
    assert body["owner_id"] == "owner-a"
    assert body["geometry_run_id"] == fixture.geometry_run_id
    assert body["geometry_run_checksum"] == summary.geometry_run_checksum
    assert body["source_identity_checksum"] == summary.source_identity_checksum
    assert body["eligibility_set_id"] == fixture.execution.eligibility_set_record_id
    assert body["eligibility_set_checksum"] == summary.eligibility_set_checksum
    assert body["planning_request_id"] == fixture.execution.planning_request_id
    assert body["planning_run_id"] == fixture.execution.planning_run_id
    assert body["observation_plan_id"] == fixture.execution.observation_plan_id
    assert body["provenance_link_id"] == fixture.execution.link_record_id
    assert body["provenance_link_checksum"] == fixture.execution.link_checksum
    assert body["status"] == OBSERVATION_STUDY_CHAIN_INTEGRITY_STATUS
    assert body["status"] == "chain-checks-consistent"
    assert body["overall_passed"] is True
    assert body["check_count"] == summary.check_count
    assert body["failed_check_count"] == 0
    assert len(body["checks"]) == summary.check_count
    assert all(check["passed"] for check in body["checks"])
    assert all(set(check) == {"name", "passed", "details"} for check in body["checks"])
    assert body["limitations"] == list(summary.limitations)
    assert body["limitations"][-1] == OBSERVATION_STUDY_CHAIN_INTEGRITY_LIMITATION
    assert body["disclaimer"] == OBSERVATION_STUDY_CHAIN_INTEGRITY_DISCLAIMER
    assert "checksum and stored-record consistency" in body["limitations"][-1]
    assert "does not prove live tracking" in body["disclaimer"]
    _assert_no_raw_study_text(response.text)


def test_observation_study_integrity_summary_api_rejects_query_shape(
    container: AppContainer,
) -> None:
    fixture = _persist_study_chain(container, site_id="SITE-STUDY-INTEGRITY-QUERY")
    route = f"{BASE}/geometry-planning-chain/integrity-summary"
    invalid_params: tuple[dict[str, str], ...] = (
        {"geometry_run_id": f" {fixture.geometry_run_id}", "provenance_link_id": "L1"},
        {"geometry_run_id": fixture.geometry_run_id, "provenance_link_id": " bad"},
        {"geometry_run_id": "", "provenance_link_id": fixture.execution.link_record_id},
        {"geometry_run_id": "G" * 121, "provenance_link_id": fixture.execution.link_record_id},
        {**_chain_params(fixture), "owner_id": "owner-b"},
        {**_chain_params(fixture), "result_json": "{}"},
        {**_chain_params(fixture), "request_json": "{}"},
        {**_chain_params(fixture), "link_json": "{}"},
        {**_chain_params(fixture), "samples": "[]"},
        {**_chain_params(fixture), "intervals": "[]"},
        {**_chain_params(fixture), "tle_line1": "1 "},
        {**_chain_params(fixture), "tle_line2": "2 "},
        {**_chain_params(fixture), "unknown": "field"},
    )

    with _owner_client(container, "owner-a") as client:
        missing_geometry = client.get(
            route,
            params={"provenance_link_id": fixture.execution.link_record_id},
        )
        missing_link = client.get(
            route,
            params={"geometry_run_id": fixture.geometry_run_id},
        )
        rejected = [client.get(route, params=params) for params in invalid_params]

    assert missing_geometry.status_code == 422
    assert missing_link.status_code == 422
    for response in rejected:
        assert response.status_code == 422
        _assert_safe_error(response)


def test_observation_study_integrity_summary_api_owner_isolation_and_mismatch_errors(
    container: AppContainer,
) -> None:
    route = f"{BASE}/geometry-planning-chain/integrity-summary"
    owner_a = _persist_study_chain(container, owner_id="owner-a", site_id="SITE-INT-A")
    owner_a_other = _persist_study_chain(container, owner_id="owner-a", site_id="SITE-INT-B")
    owner_b = _persist_study_chain(container, owner_id="owner-b", site_id="SITE-INT-C")

    with _owner_client(container, "owner-b") as client:
        hidden_geometry = client.get(route, params=_chain_params(owner_a))
        hidden_link = client.get(
            route,
            params={
                "geometry_run_id": owner_b.geometry_run_id,
                "provenance_link_id": owner_a.execution.link_record_id,
            },
        )

    with _owner_client(container, "owner-a") as client:
        mismatch = client.get(
            route,
            params={
                "geometry_run_id": owner_a.geometry_run_id,
                "provenance_link_id": owner_a_other.execution.link_record_id,
            },
        )

    assert hidden_geometry.status_code == 404
    assert hidden_link.status_code == 404
    for response in (hidden_geometry, hidden_link):
        assert response.json()["code"] == "not_found"
        assert owner_a.geometry_run_id not in response.text
        assert owner_a.execution.link_record_id not in response.text
        assert owner_a.execution.link_checksum not in response.text
        _assert_safe_error(response)
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "validation_error"
    assert "chain-checks-consistent" not in mismatch.text
    _assert_safe_error(mismatch)


def test_observation_study_integrity_summary_api_tamper_errors_are_sanitized(
    container: AppContainer,
) -> None:
    route = f"{BASE}/geometry-planning-chain/integrity-summary"
    geometry_fixture = _persist_study_chain(container, site_id="SITE-INT-TAMPER-GEOM")
    with container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, geometry_fixture.geometry_run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("api-study-integrity-tampered-geometry")
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        geometry_tamper = client.get(route, params=_chain_params(geometry_fixture))

    provenance_fixture = _persist_study_chain(container, site_id="SITE-INT-TAMPER-PROV")
    with container.database.session() as session:
        row = session.get(
            ObservationInputProvenanceRow,
            provenance_fixture.execution.provenance_record_id,
        )
        assert row is not None
        row.verification_status = "unknown"
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        provenance_tamper = client.get(route, params=_chain_params(provenance_fixture))

    eligibility_fixture = _persist_study_chain(container, site_id="SITE-INT-TAMPER-WINDOW")
    with container.database.session() as session:
        row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id
                == eligibility_fixture.execution.eligibility_set_record_id
            )
        )
        assert row is not None
        row.target_id = "TARGET-TAMPERED"
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        eligibility_tamper = client.get(route, params=_chain_params(eligibility_fixture))

    link_fixture = _persist_study_chain(container, site_id="SITE-INT-TAMPER-LINK")
    with container.database.session() as session:
        row = session.get(
            ObservationPlanningProvenanceLinkRow,
            link_fixture.execution.link_record_id,
        )
        assert row is not None
        row.selected_window_ids_json = ["missing-window"]
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        link_tamper = client.get(route, params=_chain_params(link_fixture))

    planning_fixture = _persist_study_chain(container, site_id="SITE-INT-TAMPER-PLAN")
    with container.database.session() as session:
        row = session.get(ObservationPlanningRunRow, planning_fixture.execution.planning_run_id)
        assert row is not None
        row.scientific_identity_checksum = sha256_text("api-study-integrity-tampered-planning")
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        planning_tamper = client.get(route, params=_chain_params(planning_fixture))

    for response in (
        geometry_tamper,
        provenance_tamper,
        eligibility_tamper,
        link_tamper,
        planning_tamper,
    ):
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert "chain-checks-consistent" not in response.text
        _assert_safe_error(response)


def test_observation_study_api_rejects_malformed_and_unknown_query_params(
    container: AppContainer,
) -> None:
    fixture = _persist_study_chain(container)
    invalid_params: tuple[dict[str, str], ...] = (
        {"geometry_run_id": f" {fixture.geometry_run_id}", "provenance_link_id": "L1"},
        {"geometry_run_id": fixture.geometry_run_id, "provenance_link_id": " bad"},
        {"geometry_run_id": "", "provenance_link_id": fixture.execution.link_record_id},
        {"geometry_run_id": "G" * 121, "provenance_link_id": fixture.execution.link_record_id},
        {**_chain_params(fixture), "owner_id": "owner-b"},
        {**_chain_params(fixture), "result_json": "{}"},
        {**_chain_params(fixture), "request_json": "{}"},
        {**_chain_params(fixture), "samples": "[]"},
        {**_chain_params(fixture), "intervals": "[]"},
        {**_chain_params(fixture), "tle_line1": "1 "},
        {**_chain_params(fixture), "tle_line2": "2 "},
        {**_chain_params(fixture), "unknown": "field"},
    )

    with _owner_client(container, "owner-a") as client:
        missing_geometry = client.get(
            f"{BASE}/geometry-planning-chain",
            params={"provenance_link_id": fixture.execution.link_record_id},
        )
        missing_link = client.get(
            f"{BASE}/geometry-planning-chain",
            params={"geometry_run_id": fixture.geometry_run_id},
        )
        rejected = [
            client.get(f"{BASE}/geometry-planning-chain", params=params)
            for params in invalid_params
        ]

    assert missing_geometry.status_code == 422
    assert missing_link.status_code == 422
    for response in rejected:
        assert response.status_code == 422
        _assert_safe_error(response)


def test_observation_study_api_owner_isolation_and_mismatch_errors(
    container: AppContainer,
) -> None:
    owner_a = _persist_study_chain(container, owner_id="owner-a", site_id="SITE-STUDY-A")
    owner_a_other = _persist_study_chain(container, owner_id="owner-a", site_id="SITE-STUDY-B")
    owner_b = _persist_study_chain(container, owner_id="owner-b", site_id="SITE-STUDY-C")

    with _owner_client(container, "owner-b") as client:
        hidden_geometry = client.get(
            f"{BASE}/geometry-planning-chain",
            params=_chain_params(owner_a),
        )
        hidden_link = client.get(
            f"{BASE}/geometry-planning-chain",
            params={
                "geometry_run_id": owner_b.geometry_run_id,
                "provenance_link_id": owner_a.execution.link_record_id,
            },
        )

    with _owner_client(container, "owner-a") as client:
        mismatch = client.get(
            f"{BASE}/geometry-planning-chain",
            params={
                "geometry_run_id": owner_a.geometry_run_id,
                "provenance_link_id": owner_a_other.execution.link_record_id,
            },
        )

    assert hidden_geometry.status_code == 404
    assert hidden_link.status_code == 404
    for response in (hidden_geometry, hidden_link):
        assert response.json()["code"] == "not_found"
        assert owner_a.geometry_run_id not in response.text
        assert owner_a.execution.link_record_id not in response.text
        assert owner_a.execution.link_checksum not in response.text
        _assert_safe_error(response)
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "validation_error"
    _assert_safe_error(mismatch)


def test_observation_study_api_tamper_errors_are_sanitized(
    container: AppContainer,
) -> None:
    geometry_fixture = _persist_study_chain(container, site_id="SITE-API-TAMPER-GEOM")
    with container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, geometry_fixture.geometry_run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("api-study-tampered-geometry")
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        geometry_tamper = client.get(
            f"{BASE}/geometry-planning-chain",
            params=_chain_params(geometry_fixture),
        )

    provenance_fixture = _persist_study_chain(container, site_id="SITE-API-TAMPER-PROV")
    with container.database.session() as session:
        row = session.get(
            ObservationInputProvenanceRow,
            provenance_fixture.execution.provenance_record_id,
        )
        assert row is not None
        row.verification_status = "unknown"
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        provenance_tamper = client.get(
            f"{BASE}/geometry-planning-chain",
            params=_chain_params(provenance_fixture),
        )

    eligibility_fixture = _persist_study_chain(container, site_id="SITE-API-TAMPER-WINDOW")
    with container.database.session() as session:
        row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id
                == eligibility_fixture.execution.eligibility_set_record_id
            )
        )
        assert row is not None
        row.target_id = "TARGET-TAMPERED"
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        eligibility_tamper = client.get(
            f"{BASE}/geometry-planning-chain",
            params=_chain_params(eligibility_fixture),
        )

    link_fixture = _persist_study_chain(container, site_id="SITE-API-TAMPER-LINK")
    with container.database.session() as session:
        row = session.get(
            ObservationPlanningProvenanceLinkRow,
            link_fixture.execution.link_record_id,
        )
        assert row is not None
        row.selected_window_ids_json = ["missing-window"]
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        link_tamper = client.get(
            f"{BASE}/geometry-planning-chain",
            params=_chain_params(link_fixture),
        )

    planning_fixture = _persist_study_chain(container, site_id="SITE-API-TAMPER-PLAN")
    with container.database.session() as session:
        row = session.get(ObservationPlanningRunRow, planning_fixture.execution.planning_run_id)
        assert row is not None
        row.scientific_identity_checksum = sha256_text("api-study-tampered-planning-run")
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        planning_tamper = client.get(
            f"{BASE}/geometry-planning-chain",
            params=_chain_params(planning_fixture),
        )

    for response in (
        geometry_tamper,
        provenance_tamper,
        eligibility_tamper,
        link_tamper,
        planning_tamper,
    ):
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        _assert_safe_error(response)


def test_observation_study_api_openapi_and_router_boundary(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    route = f"{BASE}/geometry-planning-chain"
    integrity_route = f"{BASE}/geometry-planning-chain/integrity-summary"
    assert route in paths
    assert integrity_route in paths
    assert set(paths[route]) == {"get"}
    assert set(paths[integrity_route]) == {"get"}
    study_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith(BASE)
        for method in methods
    }
    assert study_routes == {(route, "get"), (integrity_route, "get")}

    router_source = Path(observation_studies_router.__file__).read_text(encoding="utf-8")
    assert "get_geometry_planning_study_chain(" in router_source
    assert "summarize_geometry_planning_study_chain(" in router_source
    for forbidden in (
        "compute_observation_geometry(",
        "execute_and_persist_geometry(",
        "derive_eligibility_from_geometry_run(",
        "execute_provenance_anchored_planning(",
        "plan_observation_request(",
        "orbitmind.observation_geometry.service",
        "orbitmind.observation_geometry.persistence_service",
        "orbitmind.observation_planning.geometry_eligibility_adapter",
        "orbitmind.observation_planning.provenance_execution",
        "orbitmind.observation_planning.orchestration",
        "orbitmind.optimization.solvers",
        "orbitmind.sources.celestrak",
        "orbitmind.quantum",
        "qiskit",
        ".begin(",
        ".commit(",
        ".rollback(",
        ".flush(",
    ):
        assert forbidden not in router_source

    tree = ast.parse(router_source)
    forbidden_import_prefixes = (
        "orbitmind.observation_geometry",
        "orbitmind.observation_planning",
        "orbitmind.optimization",
        "orbitmind.sources",
        "orbitmind.quantum",
        "httpx",
        "requests",
    )
    allowed_imports = {"orbitmind.observation_studies"}
    for node in ast.walk(tree):
        module = _imported_module(node)
        if module is None or module in allowed_imports:
            continue
        assert not module.startswith(forbidden_import_prefixes), module


def test_observation_study_api_delegates_to_query_function(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _persist_study_chain(container)
    with container.database.session() as session:
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )
    calls: list[tuple[str, str, str]] = []

    def fake_query(
        session: Session,
        owner_id: str,
        *,
        geometry_run_id: str,
        provenance_link_id: str,
    ) -> ObservationStudyChain:
        assert session is not None
        calls.append((owner_id, geometry_run_id, provenance_link_id))
        return chain

    monkeypatch.setattr(observation_studies_router, "get_geometry_planning_study_chain", fake_query)
    with _owner_client(container, "owner-a") as client:
        response = client.get(f"{BASE}/geometry-planning-chain", params=_chain_params(fixture))

    assert response.status_code == 200
    assert calls == [("owner-a", fixture.geometry_run_id, fixture.execution.link_record_id)]


def test_observation_study_integrity_summary_api_delegates_to_summary_function(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _persist_study_chain(container, site_id="SITE-STUDY-INTEGRITY-DELEGATE")
    with container.database.session() as session:
        summary = summarize_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )
    calls: list[tuple[str, str, str]] = []

    def fake_summary(
        session: Session,
        owner_id: str,
        *,
        geometry_run_id: str,
        provenance_link_id: str,
    ) -> object:
        assert session is not None
        calls.append((owner_id, geometry_run_id, provenance_link_id))
        return summary

    monkeypatch.setattr(
        observation_studies_router,
        "summarize_geometry_planning_study_chain",
        fake_summary,
    )
    with _owner_client(container, "owner-a") as client:
        response = client.get(
            f"{BASE}/geometry-planning-chain/integrity-summary",
            params=_chain_params(fixture),
        )

    assert response.status_code == 200
    assert response.json()["status"] == "chain-checks-consistent"
    assert calls == [("owner-a", fixture.geometry_run_id, fixture.execution.link_record_id)]


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
