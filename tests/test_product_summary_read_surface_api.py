"""API tests for the Product Summary Read Surface boundary."""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import orbitmind.observation_studies as observation_studies_module
from orbitmind.api.map_orbit_context_schemas import MAP_ORBIT_CONTEXT_SCHEMA_VERSION
from orbitmind.api.provenance_graph_schemas import PROVENANCE_GRAPH_SCHEMA_VERSION
from orbitmind.api.routers import product_summaries as product_summaries_router
from orbitmind.api.static_report_schemas import STATIC_REPORT_SCHEMA_VERSION
from orbitmind.api.visual_manifest_schemas import (
    VISUAL_MANIFEST_SCHEMA_VERSION,
    MissionVisualManifestResponse,
    OptimizationBenchmarkVisualManifestResponse,
)
from orbitmind.optimization.service import OptimizationService
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository

BASE = "/api/v1/product-summaries/read-products"
SELF_ROUTE = ("GET", "/api/v1/product-summaries/read-products")

EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "summary_type",
    "scope_id",
    "read_at",
    "implemented_read_products",
    "deferred_read_products",
    "unsupported_read_products",
    "limitations",
    "disclaimer",
}
EXPECTED_IMPLEMENTED_FIELDS = {
    "name",
    "status",
    "route",
    "schema_version",
    "source_domain",
}
EXPECTED_DEFERRED_FIELDS = {
    "name",
    "status",
    "route",
    "contract_reference",
    "note",
}
EXPECTED_UNSUPPORTED_FIELDS = {
    "name",
    "status",
    "note",
}

EXPECTED_IMPLEMENTED_ENTRIES = {
    "GET /api/v1/visual-manifests/mission/{mission_id}": (
        "Mission visual manifest API",
        "visual-manifest-v1",
        "mission",
    ),
    "GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}": (
        "Optimization-benchmark visual manifest API",
        "visual-manifest-v1",
        "optimization-benchmark",
    ),
    "GET /api/v1/static-reports/mission/{mission_id}": (
        "Mission Static Report v1",
        "static-report-v1",
        "mission",
    ),
    "GET /api/v1/static-reports/optimization-benchmark/{benchmark_id}": (
        "Optimization Benchmark Static Report v1",
        "static-report-v1",
        "optimization-benchmark",
    ),
    "GET /api/v1/provenance-graphs/observation-study/geometry-planning-chain": (
        "Observation-study Provenance Graph API v1",
        "provenance-graph-v1",
        "observation-study",
    ),
    "GET /api/v1/map-orbit-contexts/mission/{mission_id}": (
        "Mission Map/Orbit Context v1",
        "map-orbit-context-v1",
        "mission",
    ),
}
EXPECTED_UNSUPPORTED_NAMES = {
    "rendering",
    "frontend",
    "provider-live-data",
    "exports-pdf",
    "graph-drawing",
    "map-drawing",
}


def _parsed_utc(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == dt.timedelta(0)
    return parsed


def _normalize_read_at(body: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(body)
    normalized["read_at"] = "<utc-read-time>"
    return normalized


def _assert_no_forbidden_fields(value: object) -> None:
    forbidden_keys = {
        "surface_type",
        "counts",
        "validation_status",
        "overall_status",
        "health",
        "readiness",
        "quality",
        "rank",
        "score",
        "composite_authority",
        "recommendation",
        "task",
        "command",
        "approval",
        "certification",
        "raw_evidence",
        "sidecar_json",
        "artifact_path",
        "image_bytes",
        "coordinates",
        "intervals",
        "samples",
        "tle",
        "graph_nodes",
        "graph_edges",
        "chart_data",
        "frontend_layout",
        "dashboard_ui",
        "provider_state",
        "quantum_claims",
        "qubo",
        "solver_internals",
    }
    if isinstance(value, dict):
        assert forbidden_keys.isdisjoint(value)
        for child in value.values():
            _assert_no_forbidden_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_fields(child)


def _statuses(value: object) -> set[str]:
    statuses: set[str] = set()
    if isinstance(value, dict):
        if "status" in value:
            statuses.add(str(value["status"]))
        for child in value.values():
            statuses.update(_statuses(child))
    elif isinstance(value, list):
        for child in value:
            statuses.update(_statuses(child))
    return statuses


def _openapi_read_product_routes(client: TestClient) -> set[tuple[str, str]]:
    prefixes = (
        "/api/v1/visual-manifests",
        "/api/v1/static-reports",
        "/api/v1/provenance-graphs",
        "/api/v1/map-orbit-contexts",
        "/api/v1/product-summaries",
    )
    paths = client.get("/openapi.json").json()["paths"]
    return {
        (method.upper(), path)
        for path, methods in paths.items()
        if path.startswith(prefixes)
        for method in methods
    }


def _catalog_implemented_routes(body: dict[str, Any]) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for entry in body["implemented_read_products"]:
        method, path = str(entry["route"]).split(" ", 1)
        routes.add((method, path))
    return routes


def test_product_summary_read_surface_returns_static_catalog(client: TestClient) -> None:
    response = client.get(BASE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_TOP_LEVEL_FIELDS
    assert body["schema_version"] == "product-summary-v1"
    assert body["summary_type"] == "read-product-catalog"
    assert body["scope_id"] == "orbitmind-read-products"
    _parsed_utc(body["read_at"])
    _assert_no_forbidden_fields(body)
    assert _statuses(body) == {"implemented", "deferred", "unsupported"}

    implemented = {entry["route"]: entry for entry in body["implemented_read_products"]}
    assert set(implemented) == set(EXPECTED_IMPLEMENTED_ENTRIES)
    for route, (name, schema_version, source_domain) in EXPECTED_IMPLEMENTED_ENTRIES.items():
        entry = implemented[route]
        assert set(entry) == EXPECTED_IMPLEMENTED_FIELDS
        assert entry["name"] == name
        assert entry["status"] == "implemented"
        assert entry["schema_version"] == schema_version
        assert entry["source_domain"] == source_domain

    for entry in body["deferred_read_products"]:
        assert set(entry) == EXPECTED_DEFERRED_FIELDS
        assert entry["status"] == "deferred"
    deferred = {entry["name"]: entry for entry in body["deferred_read_products"]}
    observation_manifest = deferred["Observation-study visual manifest"]
    assert observation_manifest["route"] == (
        "GET /api/v1/visual-manifests/observation-study/{geometry_run_id}/{provenance_link_id}"
    )
    assert observation_manifest["contract_reference"] == (
        "OBSERVATION_STUDY_VISUAL_MANIFEST_CONTRACT.md"
    )
    assert "not authorized" in observation_manifest["note"]
    assert "final gate not satisfied" in observation_manifest["note"]
    assert "Surface B" in observation_manifest["note"]
    assert "Surface B per-scope composition" in deferred
    assert "Dashboard UI" in deferred

    for entry in body["unsupported_read_products"]:
        assert set(entry) == EXPECTED_UNSUPPORTED_FIELDS
        assert entry["status"] == "unsupported"
    unsupported = {entry["name"] for entry in body["unsupported_read_products"]}
    assert unsupported == EXPECTED_UNSUPPORTED_NAMES

    assert "static capability declaration" in body["disclaimer"]
    assert "not evidence" in body["disclaimer"]
    assert "not proof" in body["disclaimer"]
    assert "not dashboard UI" in body["disclaimer"]
    assert any("reads no persisted domain data" in item for item in body["limitations"])
    assert any(
        "Surface B per-scope composition remains deferred" in item for item in body["limitations"]
    )
    assert any(
        "observation-study visual manifest remains deferred" in item for item in body["limitations"]
    )


def test_product_summary_read_surface_schema_versions_match_live_constants(
    client: TestClient,
) -> None:
    body = client.get(BASE).json()
    implemented = {entry["route"]: entry for entry in body["implemented_read_products"]}

    assert (
        implemented["GET /api/v1/visual-manifests/mission/{mission_id}"]["schema_version"]
        == VISUAL_MANIFEST_SCHEMA_VERSION
    )
    assert (
        implemented["GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}"][
            "schema_version"
        ]
        == VISUAL_MANIFEST_SCHEMA_VERSION
    )
    assert (
        implemented["GET /api/v1/static-reports/mission/{mission_id}"]["schema_version"]
        == STATIC_REPORT_SCHEMA_VERSION
    )
    assert (
        implemented["GET /api/v1/static-reports/optimization-benchmark/{benchmark_id}"][
            "schema_version"
        ]
        == STATIC_REPORT_SCHEMA_VERSION
    )
    assert (
        implemented["GET /api/v1/provenance-graphs/observation-study/geometry-planning-chain"][
            "schema_version"
        ]
        == PROVENANCE_GRAPH_SCHEMA_VERSION
    )
    assert (
        implemented["GET /api/v1/map-orbit-contexts/mission/{mission_id}"]["schema_version"]
        == MAP_ORBIT_CONTEXT_SCHEMA_VERSION
    )


@pytest.mark.parametrize(
    "param",
    [
        "owner_id",
        "principal",
        "user_id",
        "render",
        "renderer",
        "provider",
        "live",
        "live_data",
        "export",
        "pdf",
        "chart",
        "map",
        "dashboard",
        "format",
        "include_related",
        "include_diagnostics",
    ],
)
def test_product_summary_read_surface_rejects_every_query_param(
    client: TestClient, param: str
) -> None:
    response = client.get(BASE, params={param: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert set(response.json()) == {"code", "message"}
    for forbidden in EXPECTED_TOP_LEVEL_FIELDS:
        assert forbidden not in response.text


def test_product_summary_read_surface_is_deterministic_except_read_at(
    client: TestClient,
) -> None:
    first = client.get(BASE)
    second = client.get(BASE)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert _normalize_read_at(first.json()) == _normalize_read_at(second.json())


def test_product_summary_read_surface_uses_no_domain_data_or_self_calls(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unexpected domain data read or self-call")

    monkeypatch.setattr(SqlAlchemyMissionRepository, "get_mission", fail)
    monkeypatch.setattr(OptimizationService, "read_benchmark_evidence", fail)
    monkeypatch.setattr(observation_studies_module, "get_geometry_planning_study_chain", fail)
    monkeypatch.setattr(MissionVisualManifestResponse, "from_mission", fail)
    monkeypatch.setattr(
        OptimizationBenchmarkVisualManifestResponse,
        "from_authenticated_benchmark",
        fail,
    )

    response = client.get(BASE)

    assert response.status_code == 200, response.text
    assert len(response.json()["implemented_read_products"]) == 6


def test_product_summary_shape_differs_from_individual_read_products(client: TestClient) -> None:
    product_fields = EXPECTED_TOP_LEVEL_FIELDS
    visual_manifest_fields = {
        "schema_version",
        "manifest_id",
        "read_at",
        "source_domain",
        "scope_id",
        "items",
    }
    static_report_fields = {
        "schema_version",
        "report_id",
        "read_at",
        "source_domain",
        "scope_id",
        "report_status",
        "inputs_and_provenance",
        "mission_summary",
        "evidence_and_limitations",
        "appendix",
        "limitations",
        "disclaimer",
    }
    provenance_graph_fields = {
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
    map_orbit_context_fields = {
        "schema_version",
        "context_id",
        "read_at",
        "source_domain",
        "scope_id",
        "context_type",
        "inputs_and_provenance",
        "map_context",
        "orbit_context",
        "evidence_status",
        "limitations",
        "disclaimer",
    }

    assert set(client.get(BASE).json()) == product_fields
    assert product_fields != visual_manifest_fields
    assert product_fields != static_report_fields
    assert product_fields != provenance_graph_fields
    assert product_fields != map_orbit_context_fields


def test_product_summary_openapi_catalog_consistency_and_router_boundary(
    client: TestClient,
) -> None:
    response = client.get(BASE)
    assert response.status_code == 200, response.text
    body = response.json()

    openapi_routes = _openapi_read_product_routes(client)
    product_routes = {
        route for route in openapi_routes if route[1].startswith("/api/v1/product-summaries")
    }
    assert product_routes == {SELF_ROUTE}

    excluded_self_routes = {route for route in openapi_routes if route == SELF_ROUTE}
    # Self-route exclusion is exact: only GET /api/v1/product-summaries/read-products is excluded.
    assert excluded_self_routes == {SELF_ROUTE}
    assert len(excluded_self_routes) == 1

    catalog_routes = _catalog_implemented_routes(body)
    assert SELF_ROUTE not in catalog_routes
    assert catalog_routes.issubset(openapi_routes)
    assert openapi_routes - excluded_self_routes == catalog_routes

    router_source = Path(product_summaries_router.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "orbitmind.persistence",
        "orbitmind.mission",
        "orbitmind.optimization",
        "orbitmind.observation_studies",
        "orbitmind.api.visual_manifest_schemas",
        "orbitmind.api.static_report_schemas",
        "orbitmind.api.provenance_graph_schemas",
        "orbitmind.api.map_orbit_context_schemas",
        "orbitmind.visualization",
        "orbitmind.sources",
        "orbitmind.quantum",
        "frontend",
        "dashboard",
        "provider",
        "live_data",
        "live-data",
        ".begin(",
        ".commit(",
        ".rollback(",
        ".flush(",
    ):
        assert forbidden not in router_source.lower()

    tree = ast.parse(router_source)
    forbidden_import_prefixes = (
        "orbitmind.persistence",
        "orbitmind.mission",
        "orbitmind.optimization",
        "orbitmind.observation_studies",
        "orbitmind.api.visual_manifest_schemas",
        "orbitmind.api.static_report_schemas",
        "orbitmind.api.provenance_graph_schemas",
        "orbitmind.api.map_orbit_context_schemas",
        "orbitmind.visualization",
        "orbitmind.sources",
        "orbitmind.quantum",
        "httpx",
        "requests",
    )
    for node in ast.walk(tree):
        module = _imported_module(node)
        if module is None:
            continue
        assert not module.startswith(forbidden_import_prefixes), module


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.ImportFrom):
        return node.module
    if isinstance(node, ast.Import) and node.names:
        return node.names[0].name
    return None
