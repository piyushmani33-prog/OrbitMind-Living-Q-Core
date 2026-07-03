"""API tests for the mission Map/Orbit Context boundary."""

from __future__ import annotations

import ast
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import orbitmind.orchestration.orchestrator as orchestrator_module
import orbitmind.sources.registry as registry_module
import orbitmind.visualization.charts as charts_module
from orbitmind.api.container import AppContainer
from orbitmind.api.routers import map_orbit_contexts as map_orbit_contexts_router
from orbitmind.persistence.models import ArtifactRow

BASE = "/api/v1/map-orbit-contexts/mission"
MISSION_ENDPOINT = "/api/v1/missions/orbit-propagation"
VISUAL_MANIFEST_BASE = "/api/v1/visual-manifests/mission"
STATIC_REPORT_BASE = "/api/v1/static-reports/mission"

EXPECTED_TOP_LEVEL_FIELDS = {
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
EXPECTED_INPUT_FIELDS = {
    "manifest_id",
    "manifest_schema_version",
    "manifest_source_domain",
    "manifest_scope_id",
    "mission_record_handle",
    "artifact_handles",
    "checksum_handles",
    "source_labels",
}
EXPECTED_CONTEXT_FIELDS = {
    "context_kind",
    "artifact_handles",
    "checksum_handles",
    "source_labels",
    "limitations",
    "coordinate_payloads",
}
EXPECTED_EVIDENCE_FIELDS = {
    "status",
    "withheld",
    "coordinate_payloads",
    "authority_boundaries",
    "limitations",
}


def _create_mission(client: TestClient, payload: dict[str, object]) -> str:
    response = client.post(MISSION_ENDPOINT, json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["mission_id"])


def _assert_safe_context_text(text: str) -> None:
    lowered = text.lower()
    for forbidden in (
        '"path"',
        '"sidecar_path"',
        '"url"',
        '"artifact_type"',
        "source_references",
        "tle_line",
        "raw coordinate",
        "raw trajectory",
        "raw sample",
        "raw interval",
        "trajectory array",
        "coordinate stream",
        "postgresql://",
        "select ",
        "insert ",
        "traceback",
        ".py",
        "execution_receipt",
        "receipt_status",
        '"signature"',
        "hmac",
        "quantum_evidence",
        "qubo",
        "solver internals",
        "provider state",
        "cached provider",
        "basemap url",
        "tile url",
    ):
        assert forbidden not in lowered


def _assert_no_forbidden_fields(value: object) -> None:
    forbidden_keys = {
        "samples",
        "intervals",
        "coordinates",
        "trajectories",
        "tle_line1",
        "tle_line2",
        "path",
        "sidecar_path",
        "sidecar_json",
        "image_bytes",
        "png_bytes",
        "provider_state",
        "receipt_status",
        "signature",
        "hmac",
        "quantum_evidence",
        "qubo",
        "solver_internals",
        "command",
        "recommendation",
    }
    if isinstance(value, dict):
        assert forbidden_keys.isdisjoint(value)
        for child in value.values():
            _assert_no_forbidden_fields(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_forbidden_fields(child)


def _assert_safe_error(response: Any) -> None:
    assert set(response.json()) == {"code", "message"}
    _assert_safe_context_text(response.text)
    for forbidden in (
        "schema_version",
        "context_id",
        "scope_id",
        "context_type",
        "inputs_and_provenance",
        "map_context",
        "orbit_context",
        "evidence_status",
        "limitations",
        "disclaimer",
        "constraint",
        "artifact_records",
        "sidecar",
        "not-a-checksum",
    ):
        assert forbidden not in response.text.lower()


def _parsed_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    return parsed


def test_mission_map_orbit_context_returns_safe_coordinate_free_json(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_TOP_LEVEL_FIELDS
    assert body["schema_version"] == "map-orbit-context-v1"
    assert body["source_domain"] == "mission"
    assert body["scope_id"] == f"mission:{mission_id}"
    assert body["context_id"] == f"map-orbit-context:mission:{mission_id}:v1"
    assert body["context_type"] == "mission-map-orbit-context"
    _parsed_utc(body["read_at"])

    assert set(body["inputs_and_provenance"]) == EXPECTED_INPUT_FIELDS
    assert body["inputs_and_provenance"]["manifest_id"] == (
        f"visual-manifest:mission:{mission_id}:v1"
    )
    assert body["inputs_and_provenance"]["manifest_schema_version"] == "visual-manifest-v1"
    assert body["inputs_and_provenance"]["manifest_source_domain"] == "mission"
    assert body["inputs_and_provenance"]["manifest_scope_id"] == mission_id
    assert body["inputs_and_provenance"]["mission_record_handle"] == f"mission:{mission_id}"
    assert len(body["inputs_and_provenance"]["artifact_handles"]) == 2
    assert len(body["inputs_and_provenance"]["checksum_handles"]) == 2

    assert set(body["map_context"]) == EXPECTED_CONTEXT_FIELDS
    assert body["map_context"]["context_kind"] == "mission-ground-track-context"
    assert len(body["map_context"]["artifact_handles"]) == 1
    assert body["map_context"]["artifact_handles"][0].startswith("mission-artifact:")
    assert body["map_context"]["checksum_handles"][0].startswith("sha256:")
    assert body["map_context"]["coordinate_payloads"] == "excluded-by-design-in-v1"

    assert set(body["orbit_context"]) == EXPECTED_CONTEXT_FIELDS
    assert body["orbit_context"]["context_kind"] == "mission-orbit-context"
    assert len(body["orbit_context"]["artifact_handles"]) == 1
    assert body["orbit_context"]["artifact_handles"][0].startswith("mission-artifact:")
    assert body["orbit_context"]["checksum_handles"][0].startswith("sha256:")
    assert body["orbit_context"]["coordinate_payloads"] == "excluded-by-design-in-v1"

    assert set(body["evidence_status"]) == EXPECTED_EVIDENCE_FIELDS
    assert body["evidence_status"]["status"] == "available"
    assert body["evidence_status"]["withheld"] is False
    assert body["evidence_status"]["coordinate_payloads"] == "excluded-by-design-in-v1"
    for boundary in (
        "no live tracking",
        "no real-time position authority",
        "no provider/live-data",
        "no rendering",
        "no operational access",
        "no taskability",
        "no command readiness",
        "no approval",
        "no certification",
        "no signed receipt authority",
        "no operational recommendation",
        "no quantum authority",
        "no general quantum advantage",
    ):
        assert boundary in body["evidence_status"]["authority_boundaries"]

    assert "coordinate-free" in " ".join(body["limitations"])
    assert "not proof by itself" in body["disclaimer"]
    assert "not evidence by itself" in body["disclaimer"]
    assert "not live tracking" in body["disclaimer"]
    assert "not provider/live-data behavior" in body["disclaimer"]
    assert "not rendering" in body["disclaimer"]
    _assert_safe_context_text(response.text)
    _assert_no_forbidden_fields(body)


@pytest.mark.parametrize(
    "mission_id",
    [
        "not-a-uuid",
        "..escape",
        "E:%5Cquantum-project",
        "11111111222233334444555555555555",
    ],
)
def test_mission_map_orbit_context_rejects_malformed_path_like_ids(
    client: TestClient,
    mission_id: str,
) -> None:
    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_map_orbit_context_missing_mission_returns_404(client: TestClient) -> None:
    response = client.get(f"{BASE}/11111111-2222-3333-4444-555555555555")

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    _assert_safe_error(response)


@pytest.mark.parametrize(
    "param",
    [
        "owner_id",
        "principal",
        "user_id",
        "render",
        "renderer",
        "layer",
        "tile",
        "basemap",
        "terrain",
        "imagery",
        "provider",
        "live",
        "live_data",
        "include_related",
        "include_diagnostics",
        "path",
        "sidecar",
        "sql",
        "result_json",
        "request_json",
        "link_json",
        "locator",
        "format",
    ],
)
def test_mission_map_orbit_context_rejects_every_query_param(
    client: TestClient,
    iss_request: dict[str, object],
    param: str,
) -> None:
    mission_id = _create_mission(client, iss_request)

    response = client.get(f"{BASE}/{mission_id}", params={param: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_map_orbit_context_does_not_need_sidecar_or_png_files(
    client: TestClient,
    container: AppContainer,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)
    shutil.rmtree(container.settings.resolved_artifacts_dir())

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    assert response.json()["scope_id"] == f"mission:{mission_id}"
    _assert_safe_context_text(response.text)


def test_mission_map_orbit_context_subset_output_types_keeps_both_sections(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, {**iss_request, "output_types": ["ground_track"]})

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["map_context"]["artifact_handles"]
    assert body["map_context"]["checksum_handles"]
    assert body["orbit_context"]["artifact_handles"] == []
    assert body["orbit_context"]["checksum_handles"] == []
    assert (
        "no reviewed artifact of type altitude_vs_time exists"
        in " ".join(body["orbit_context"]["limitations"]).lower()
    )
    assert body["orbit_context"]["coordinate_payloads"] == "excluded-by-design-in-v1"
    assert body["evidence_status"]["withheld"] is False


def test_mission_map_orbit_context_does_not_recompute_regenerate_or_fetch(
    client: TestClient,
    iss_request: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mission_id = _create_mission(client, iss_request)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unexpected recomputation, regeneration, or fetch")

    monkeypatch.setattr(charts_module.VisualizationService, "render", fail)
    monkeypatch.setattr(orchestrator_module.PrimeOrchestrator, "run_orbit_mission", fail)
    monkeypatch.setattr(registry_module.SourceRegistry, "get_tle", fail)

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    assert response.json()["scope_id"] == f"mission:{mission_id}"


def test_mission_map_orbit_context_malformed_persisted_checksum_is_sanitized_422(
    client: TestClient,
    container: AppContainer,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)
    with container.database.session() as session:
        row = (
            session.execute(select(ArtifactRow).where(ArtifactRow.mission_id == mission_id))
            .scalars()
            .first()
        )
        assert row is not None
        row.checksum = "not-a-checksum"
        session.commit()

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_map_orbit_context_is_deterministic_except_read_at(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    first = client.get(f"{BASE}/{mission_id}")
    second = client.get(f"{BASE}/{mission_id}")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_body = first.json()
    second_body = second.json()
    first_body["read_at"] = "<utc-read-time>"
    second_body["read_at"] = "<utc-read-time>"
    assert first_body == second_body


def test_mission_map_orbit_context_matches_live_visual_manifest_projection(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{mission_id}")
    context = client.get(f"{BASE}/{mission_id}")

    assert manifest.status_code == 200, manifest.text
    assert context.status_code == 200, context.text
    manifest_body = manifest.json()
    context_body = context.json()
    artifact_handles = [item["artifact_handle"] for item in manifest_body["items"]]
    checksum_handles = [item["checksum_handle"] for item in manifest_body["items"]]
    source_labels = sorted(
        {label for item in manifest_body["items"] for label in item["source_labels"]}
    )
    assert context_body["inputs_and_provenance"]["manifest_id"] == manifest_body["manifest_id"]
    assert context_body["inputs_and_provenance"]["manifest_scope_id"] == mission_id
    assert context_body["inputs_and_provenance"]["artifact_handles"] == artifact_handles
    assert context_body["inputs_and_provenance"]["checksum_handles"] == checksum_handles
    assert sorted(context_body["inputs_and_provenance"]["source_labels"]) == source_labels


def test_mission_map_orbit_context_shape_differs_from_sibling_read_products(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{mission_id}").json()
    report = client.get(f"{STATIC_REPORT_BASE}/{mission_id}").json()
    context = client.get(f"{BASE}/{mission_id}").json()

    assert set(context) == EXPECTED_TOP_LEVEL_FIELDS
    assert set(context) != set(manifest)
    assert set(context) != set(report)
    assert "items" not in context
    assert "mission_summary" not in context
    assert "map_context" in context
    assert "orbit_context" in context


def test_mission_map_orbit_context_openapi_and_router_boundary(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    route = "/api/v1/map-orbit-contexts/mission/{mission_id}"
    assert route in paths
    assert set(paths[route]) == {"get"}
    context_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith("/api/v1/map-orbit-contexts")
        for method in methods
    }
    assert context_routes == {(route, "get")}
    assert "/api/v1/map-orbit-contexts/{domain}/{scope_id}" not in paths

    router_source = Path(map_orbit_contexts_router.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "orbitmind.visualization",
        "orbitmind.space.propagation",
        "orbitmind.sources.celestrak",
        "orbitmind.sources.jpl",
        "orbitmind.optimization",
        "orbitmind.quantum",
        "qiskit",
        "frontend",
        "dashboard",
        "leaflet",
        "cesium",
        "d3",
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
        "orbitmind.visualization",
        "orbitmind.space.propagation",
        "orbitmind.sources.celestrak",
        "orbitmind.sources.jpl",
        "orbitmind.optimization",
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
