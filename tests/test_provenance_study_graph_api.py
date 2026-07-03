"""HTTP API tests for provenance study graph projections."""

from __future__ import annotations

import ast
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import orbitmind.api.routers.provenance_graphs as provenance_graphs_router
import orbitmind.observation_geometry.persistence_service as geometry_persistence_service
import orbitmind.observation_planning.orchestration as orchestration_module
from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.provenance_graph_schemas import (
    PROVENANCE_GRAPH_DISCLAIMER,
    PROVENANCE_GRAPH_LIMITATIONS,
    ObservationStudyProvenanceGraphResponse,
)
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import ValidationError
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.models import ObservationPlanningRequest
from orbitmind.observation_planning.provenance_execution import (
    ProvenanceAnchoredPlanningExecution,
    execute_provenance_anchored_planning,
)
from orbitmind.observation_studies import get_geometry_planning_study_chain
from orbitmind.persistence.observation_geometry_models import ObservationGeometryRunRow
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationPlanningProvenanceLinkRow,
)
from orbitmind.sources.registry import SourceRegistry

BASE = "/api/v1/provenance-graphs"
ROUTE = f"{BASE}/observation-study/geometry-planning-chain"
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=dt.UTC)
TOP_LEVEL_FIELDS = {
    "schema_version",
    "graph_id",
    "read_at",
    "source_domain",
    "graph_type",
    "scope_handle",
    "owner_scope",
    "status",
    "nodes",
    "edges",
    "node_count",
    "edge_count",
    "limitations",
    "disclaimer",
}
NODE_FIELDS = {
    "node_id",
    "node_type",
    "record_handle",
    "checksum_handle",
    "status",
    "source",
    "limitations",
    "disclaimer",
}
EDGE_FIELDS = {
    "edge_id",
    "edge_type",
    "source",
    "target",
    "proof_source",
    "limitations",
    "disclaimer",
}
GRAPH_ERROR_FIELDS = {
    "graph_id",
    "scope_handle",
    "nodes",
    "edges",
    "node_count",
    "edge_count",
    "integrity_summary",
}
EXPECTED_NODE_TYPES = [
    "geometry-run",
    "eligibility-provenance",
    "eligibility-set",
    "planning-request",
    "planning-run",
    "observation-plan",
    "provenance-link",
    "integrity-summary",
]
EXPECTED_PROOF_SOURCES = {
    "recorded-provenance:derived-from-geometry",
    "recorded-fk:eligibility-set-to-provenance",
    "recorded-link:provenance-link-to-eligibility-provenance",
    "recorded-link:provenance-link-to-eligibility-set",
    "recorded-link:provenance-link-to-planning-request",
    "recorded-link:provenance-link-to-planning-run",
    "recorded-fk:planning-run-to-observation-plan",
    "recorded-summary:chain-integrity",
}


@dataclass(frozen=True)
class StudyGraphFixture:
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


def _geometry_request(site_id: str = "SITE-GRAPH-API") -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} provenance graph API test site",
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
    site_id: str = "SITE-GRAPH-API",
) -> StudyGraphFixture:
    with container.database.session() as session:
        geometry_execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=_geometry_request(site_id),
            idempotency_key=f"graph-api-geometry:{owner_id}:{site_id}",
        )
    with container.database.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id=owner_id,
            geometry_run_id=geometry_execution.run_id,
            requested_by="graph-api-analyst",
        )
    with container.database.session() as session:
        execution = execute_provenance_anchored_planning(
            session=session,
            owner_id=owner_id,
            eligibility_set_id=derived.eligibility_set_record_id,
            requested_by="graph-api-planner",
        )
    return StudyGraphFixture(
        geometry_run_id=geometry_execution.run_id,
        geometry_request_id=geometry_execution.request_id,
        execution=execution,
    )


def _params(fixture: StudyGraphFixture) -> dict[str, str]:
    return {
        "geometry_run_id": fixture.geometry_run_id,
        "provenance_link_id": fixture.execution.link_record_id,
    }


def _scope_handle(fixture: StudyGraphFixture) -> str:
    return f"observation-study-chain:{fixture.geometry_run_id}:{fixture.execution.link_record_id}"


def _normalize_read_at(body: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(body)
    normalized["read_at"] = "<read-at>"
    return normalized


def _assert_no_forbidden_text(text: str) -> None:
    lowered = text.lower()
    for forbidden in (
        "sidecar_path",
        "artifact root",
        "artifacts-root",
        "raw sidecar json",
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
        "receipt_status",
        "signature",
        "hmac",
        "quantum_evidence",
        "quantum evidence",
        "qubo",
        "solver internals",
        "provider state",
        "operational command",
        "owner-a",
        "owner-b",
    ):
        assert forbidden not in lowered


def _assert_safe_error(response: Any) -> None:
    body = response.json()
    assert set(body) == {"code", "message"}
    for field in GRAPH_ERROR_FIELDS:
        assert field not in body
        assert field not in response.text
    _assert_no_forbidden_text(response.text)


def _assert_graph_shape(body: dict[str, Any], fixture: StudyGraphFixture) -> None:
    scope_handle = _scope_handle(fixture)
    assert set(body) == TOP_LEVEL_FIELDS
    assert body["schema_version"] == "provenance-graph-v1"
    assert body["graph_id"] == f"provenance-study-graph:{scope_handle}:v1"
    assert body["source_domain"] == "observation-study"
    assert body["graph_type"] == "geometry-planning-chain"
    assert body["scope_handle"] == scope_handle
    assert body["owner_scope"] == "trusted-owner-dependency"
    assert body["status"] == "chain-checks-consistent"
    assert body["node_count"] == len(body["nodes"]) == 8
    assert body["edge_count"] == len(body["edges"]) == 8
    read_at = dt.datetime.fromisoformat(body["read_at"])
    assert read_at.tzinfo is not None
    assert read_at.utcoffset() == dt.timedelta(0)
    assert body["limitations"][: len(PROVENANCE_GRAPH_LIMITATIONS)] == list(
        PROVENANCE_GRAPH_LIMITATIONS
    )
    assert body["disclaimer"] == PROVENANCE_GRAPH_DISCLAIMER
    for phrase in (
        "A served graph means only",
        "not proof of scientific correctness",
        "not complete lineage",
        "not operational access",
        "not taskability",
        "not command readiness",
        "not approval",
        "not certification",
        "not signed receipt authority",
        "not quantum authority",
        "not a claim of general quantum advantage",
    ):
        assert phrase in body["disclaimer"]

    assert [node["node_type"] for node in body["nodes"]] == EXPECTED_NODE_TYPES
    assert all(set(node) == NODE_FIELDS for node in body["nodes"])
    assert all(node["disclaimer"] == PROVENANCE_GRAPH_DISCLAIMER for node in body["nodes"])
    assert all(node["limitations"] == list(PROVENANCE_GRAPH_LIMITATIONS) for node in body["nodes"])
    assert body["nodes"][-1]["node_id"] == f"study-graph-node:integrity-summary:{scope_handle}"
    assert body["nodes"][-1]["record_handle"] == scope_handle
    assert body["nodes"][-1]["checksum_handle"] is None
    assert "chain-checks-consistent" in body["nodes"][-1]["status"]
    assert "owner-a" not in body

    assert all(set(edge) == EDGE_FIELDS for edge in body["edges"])
    assert body["edges"] == sorted(
        body["edges"],
        key=lambda edge: (edge["edge_type"], edge["source"], edge["target"]),
    )
    assert {edge["proof_source"] for edge in body["edges"]} == EXPECTED_PROOF_SOURCES
    assert all(edge["disclaimer"] == PROVENANCE_GRAPH_DISCLAIMER for edge in body["edges"])
    assert all(edge["limitations"] == list(PROVENANCE_GRAPH_LIMITATIONS) for edge in body["edges"])
    assert all(edge["edge_id"].startswith("study-graph-edge:") for edge in body["edges"])
    assert any(
        edge["edge_type"] == "integrity-summary checks observation-study-chain"
        and edge["target"] == scope_handle
        for edge in body["edges"]
    )
    for edge in body["edges"]:
        assert edge["proof_source"].startswith(("recorded-", "recorded_"))
        assert fixture.geometry_run_id not in edge["proof_source"]
        assert fixture.execution.link_record_id not in edge["proof_source"]
        assert fixture.execution.link_checksum not in edge["proof_source"]


def test_provenance_study_graph_api_returns_safe_deterministic_graph(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _persist_study_chain(container)

    def fail_geometry_compute(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise AssertionError("graph API must not recompute geometry")

    def fail_planner(_: ObservationPlanningRequest) -> object:
        raise AssertionError("graph API must not execute planning")

    monkeypatch.setattr(
        geometry_persistence_service,
        "compute_observation_geometry",
        fail_geometry_compute,
    )
    monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)

    with _owner_client(container, "owner-a") as client:
        first = client.get(ROUTE, params=_params(fixture))
        second = client.get(ROUTE, params=_params(fixture))

    assert first.status_code == 200
    assert second.status_code == 200
    first_body = first.json()
    second_body = second.json()
    _assert_graph_shape(first_body, fixture)
    assert _normalize_read_at(first_body) == _normalize_read_at(second_body)
    _assert_no_forbidden_text(first.text)


def test_provenance_study_graph_api_query_validation(
    container: AppContainer,
) -> None:
    fixture = _persist_study_chain(container, site_id="SITE-GRAPH-QUERY")
    invalid_params: tuple[dict[str, str], ...] = (
        {"geometry_run_id": f" {fixture.geometry_run_id}", "provenance_link_id": "L1"},
        {"geometry_run_id": fixture.geometry_run_id, "provenance_link_id": " bad"},
        {"geometry_run_id": "", "provenance_link_id": fixture.execution.link_record_id},
        {"geometry_run_id": "G" * 121, "provenance_link_id": fixture.execution.link_record_id},
        {**_params(fixture), "owner_id": "owner-b"},
        {**_params(fixture), "principal": "owner-b"},
        {**_params(fixture), "user_id": "owner-b"},
        {**_params(fixture), "result_json": "{}"},
        {**_params(fixture), "request_json": "{}"},
        {**_params(fixture), "link_json": "{}"},
        {**_params(fixture), "samples": "[]"},
        {**_params(fixture), "intervals": "[]"},
        {**_params(fixture), "tle_line1": "1 "},
        {**_params(fixture), "render": "true"},
        {**_params(fixture), "layout": "dagre"},
        {**_params(fixture), "provider": "live"},
        {**_params(fixture), "live_data": "true"},
        {**_params(fixture), "unknown": "field"},
    )

    with _owner_client(container, "owner-a") as client:
        missing_geometry = client.get(
            ROUTE,
            params={"provenance_link_id": fixture.execution.link_record_id},
        )
        missing_link = client.get(ROUTE, params={"geometry_run_id": fixture.geometry_run_id})
        rejected = [client.get(ROUTE, params=params) for params in invalid_params]

    assert missing_geometry.status_code == 422
    assert missing_link.status_code == 422
    for response in (missing_geometry, missing_link):
        for field in GRAPH_ERROR_FIELDS:
            assert field not in response.text
        _assert_no_forbidden_text(response.text)
    for response in rejected:
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        _assert_safe_error(response)


def test_provenance_study_graph_api_owner_isolation_and_mismatch_errors(
    container: AppContainer,
) -> None:
    owner_a = _persist_study_chain(container, owner_id="owner-a", site_id="SITE-GRAPH-A")
    owner_a_other = _persist_study_chain(
        container,
        owner_id="owner-a",
        site_id="SITE-GRAPH-B",
    )
    owner_b = _persist_study_chain(container, owner_id="owner-b", site_id="SITE-GRAPH-C")

    with _owner_client(container, "owner-b") as client:
        hidden_geometry = client.get(ROUTE, params=_params(owner_a))
        hidden_link = client.get(
            ROUTE,
            params={
                "geometry_run_id": owner_b.geometry_run_id,
                "provenance_link_id": owner_a.execution.link_record_id,
            },
        )

    with _owner_client(container, "owner-a") as client:
        mismatch = client.get(
            ROUTE,
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
        assert "node_count" not in response.text
        assert "edge_count" not in response.text
        assert "observation-study-chain:" not in response.text
        _assert_safe_error(response)
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "validation_error"
    _assert_safe_error(mismatch)


def test_provenance_study_graph_api_tamper_errors_are_sanitized(
    container: AppContainer,
) -> None:
    geometry_fixture = _persist_study_chain(container, site_id="SITE-GRAPH-TAMPER-GEOM")
    with container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, geometry_fixture.geometry_run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("graph-api-tampered-geometry")
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        geometry_tamper = client.get(ROUTE, params=_params(geometry_fixture))

    eligibility_fixture = _persist_study_chain(
        container,
        site_id="SITE-GRAPH-TAMPER-WINDOW",
    )
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
        eligibility_tamper = client.get(ROUTE, params=_params(eligibility_fixture))

    link_fixture = _persist_study_chain(container, site_id="SITE-GRAPH-TAMPER-LINK")
    with container.database.session() as session:
        row = session.get(
            ObservationPlanningProvenanceLinkRow,
            link_fixture.execution.link_record_id,
        )
        assert row is not None
        row.selected_window_ids_json = ["missing-window"]
        session.commit()
    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        link_tamper = client.get(ROUTE, params=_params(link_fixture))

    for response in (geometry_tamper, eligibility_tamper, link_tamper):
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        _assert_safe_error(response)


def test_provenance_study_graph_projection_rejects_failed_or_partial_checks(
    container: AppContainer,
) -> None:
    fixture = _persist_study_chain(container, site_id="SITE-GRAPH-FAILED-CHECK")
    with container.database.session() as session:
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )
    failed_check = chain.checks[0].model_copy(update={"passed": False})
    failed_chain = chain.model_copy(update={"checks": (failed_check, *chain.checks[1:])})
    partial_chain = chain.model_copy(update={"checks": chain.checks[1:]})

    with pytest.raises(ValidationError, match="study graph withheld"):
        ObservationStudyProvenanceGraphResponse.from_chain(failed_chain)
    with pytest.raises(ValidationError, match="study graph withheld"):
        ObservationStudyProvenanceGraphResponse.from_chain(partial_chain)


def test_provenance_study_graph_projection_omits_absent_observation_plan(
    container: AppContainer,
) -> None:
    fixture = _persist_study_chain(container, site_id="SITE-GRAPH-NO-PLAN")
    with container.database.session() as session:
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )
    # The current service path normally persists a plan. This schema-level projection
    # fixture covers the documented optional branch without changing persisted records.
    planning_without_plan = chain.planning.model_copy(update={"observation_plan_id": None})
    response = ObservationStudyProvenanceGraphResponse.from_chain(
        chain.model_copy(update={"planning": planning_without_plan})
    )
    body = response.model_dump(mode="json")

    assert [node["node_type"] for node in body["nodes"]] == [
        "geometry-run",
        "eligibility-provenance",
        "eligibility-set",
        "planning-request",
        "planning-run",
        "provenance-link",
        "integrity-summary",
    ]
    assert not any(
        edge["edge_type"] == "planning-run produced observation-plan" for edge in body["edges"]
    )


def test_provenance_study_graph_api_openapi_and_router_boundary(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert ROUTE in paths
    assert set(paths[ROUTE]) == {"get"}
    graph_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith(BASE)
        for method in methods
    }
    assert graph_routes == {(ROUTE, "get")}

    router_source = Path(provenance_graphs_router.__file__).read_text(encoding="utf-8")
    assert "get_geometry_planning_study_chain(" in router_source
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
        "orbitmind.optimization",
        "orbitmind.sources.celestrak",
        "orbitmind.quantum",
        "qiskit",
        "d3",
        "frontend",
        "dashboard",
        "render",
        "provider",
        "live",
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


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
