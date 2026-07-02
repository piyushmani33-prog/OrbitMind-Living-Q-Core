"""API tests for the mission visual manifest boundary."""

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
from orbitmind.api.routers import visual_manifests as visual_manifests_router
from orbitmind.persistence.models import ArtifactRow

BASE = "/api/v1/visual-manifests/mission"
MISSION_ENDPOINT = "/api/v1/missions/orbit-propagation"
EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "manifest_id",
    "read_at",
    "source_domain",
    "scope_id",
    "items",
    "limitations",
    "disclaimer",
}
EXPECTED_ITEM_FIELDS = {
    "item_id",
    "item_type",
    "media_type",
    "artifact_handle",
    "checksum_handle",
    "source_record_handles",
    "canonical_epistemic_status",
    "verification_state",
    "source_labels",
    "limitations",
    "disclaimers",
    "presentation_hints",
}


def _create_mission(client: TestClient, iss_request: dict[str, object]) -> str:
    response = client.post(MISSION_ENDPOINT, json=iss_request)
    assert response.status_code == 201, response.text
    return str(response.json()["mission_id"])


def _assert_safe_manifest_text(text: str) -> None:
    forbidden = (
        '"path"',
        '"sidecar_path"',
        '"units"',
        '"url"',
        "artifact_type",
        "source_references",
        "software_versions",
        "tle_line1",
        "tle_line2",
        "result_json",
        "request_json",
        "link_json",
        "postgresql://",
        "select ",
        "insert ",
        "traceback",
        ".py",
        "e:\\",
    )
    lowered = text.lower()
    for term in forbidden:
        assert term not in lowered


def _assert_safe_error(response: Any) -> None:
    assert set(response.json()) == {"code", "message"}
    _assert_safe_manifest_text(response.text)
    for forbidden in ("constraint", "artifact_records", "sidecar", "not-a-checksum"):
        assert forbidden not in response.text.lower()


def _parsed_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    return parsed


def test_mission_visual_manifest_returns_path_free_db_only_response(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_TOP_LEVEL_FIELDS
    assert body["schema_version"] == "visual-manifest-v1"
    assert body["source_domain"] == "mission"
    assert body["scope_id"] == mission_id
    assert body["manifest_id"] == f"visual-manifest:mission:{mission_id}:v1"
    for forbidden in ("receipt", "attestation", "signature", "approval", "certification"):
        assert forbidden not in body["manifest_id"]
    _parsed_utc(body["read_at"])
    assert "not live tracking" in body["disclaimer"]
    assert "not approval" in body["disclaimer"]
    assert "database records only" in " ".join(body["limitations"])
    assert "not a receipt id" in " ".join(body["limitations"])

    assert len(body["items"]) == 2
    item_types = {item["item_type"] for item in body["items"]}
    assert item_types == {"altitude_vs_time", "ground_track"}
    for item in body["items"]:
        assert set(item) == EXPECTED_ITEM_FIELDS
        assert item["media_type"] == "image/png"
        assert item["artifact_handle"].startswith("mission-artifact:")
        assert item["checksum_handle"].startswith("sha256:")
        assert len(item["checksum_handle"].removeprefix("sha256:")) == 64
        assert item["source_record_handles"][0] == f"mission:{mission_id}"
        assert any(
            handle.startswith("source-checksum:sha256:") for handle in item["source_record_handles"]
        )
        assert item["canonical_epistemic_status"] == "deterministic-calculation"
        assert item["verification_state"] == "mission-verification-passed"
        assert "mission-source:sample" in item["source_labels"]
        assert "test-only:true" in item["source_labels"]
        assert item["presentation_hints"]["scientific_authority"] == "none-added"
        assert "sidecar scientific context" in " ".join(item["limitations"])
        assert "artifact file authentication" in " ".join(item["disclaimers"])
        for forbidden in (
            "units",
            "path",
            "sidecar_path",
            "url",
            "source_references",
            "artifact_type",
        ):
            assert forbidden not in item

    _assert_safe_manifest_text(response.text)
    for overclaim in (
        "operationally ready",
        "command ready",
        "taskable",
        "approved plan",
        "certified",
        "real-world asset",
    ):
        assert overclaim not in response.text.lower()


@pytest.mark.parametrize(
    "mission_id",
    [
        "not-a-uuid",
        "..escape",
        "E:%5Cquantum-project",
        "11111111222233334444555555555555",
    ],
)
def test_mission_visual_manifest_rejects_malformed_path_like_ids(
    client: TestClient,
    mission_id: str,
) -> None:
    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_visual_manifest_missing_mission_returns_404(client: TestClient) -> None:
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
        "include_related",
        "include_diagnostics",
        "path",
        "sidecar",
        "sql",
        "result_json",
        "request_json",
        "link_json",
        "locator",
        "provider_fetch",
        "live_data",
        "format",
    ],
)
def test_mission_visual_manifest_rejects_every_query_param(
    client: TestClient,
    iss_request: dict[str, object],
    param: str,
) -> None:
    mission_id = _create_mission(client, iss_request)

    response = client.get(f"{BASE}/{mission_id}", params={param: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_visual_manifest_does_not_need_sidecar_or_png_files(
    client: TestClient,
    container: AppContainer,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)
    shutil.rmtree(container.settings.resolved_artifacts_dir())

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope_id"] == mission_id
    assert len(body["items"]) == 2
    _assert_safe_manifest_text(response.text)


def test_mission_visual_manifest_does_not_recompute_regenerate_or_fetch(
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
    assert response.json()["scope_id"] == mission_id


def test_mission_visual_manifest_malformed_persisted_checksum_is_sanitized_422(
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


def test_mission_visual_manifest_openapi_and_router_boundary(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    route = "/api/v1/visual-manifests/mission/{mission_id}"
    optimization_route = "/api/v1/visual-manifests/optimization-benchmark/{benchmark_id}"
    assert route in paths
    assert set(paths[route]) == {"get"}
    assert optimization_route in paths
    assert set(paths[optimization_route]) == {"get"}
    visual_manifest_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith("/api/v1/visual-manifests")
        for method in methods
    }
    assert visual_manifest_routes == {(route, "get"), (optimization_route, "get")}

    router_source = Path(visual_manifests_router.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "orbitmind.visualization.charts",
        "orbitmind.space.propagation",
        "orbitmind.sources.celestrak",
        "orbitmind.sources.jpl",
        "orbitmind.optimization.solvers",
        "orbitmind.quantum",
        "qiskit",
        "report",
        "dashboard",
        "leaflet",
        "cesium",
        "d3",
        ".begin(",
        ".commit(",
        ".rollback(",
        ".flush(",
    ):
        assert forbidden not in router_source.lower()

    tree = ast.parse(router_source)
    forbidden_import_prefixes = (
        "orbitmind.visualization.charts",
        "orbitmind.space.propagation",
        "orbitmind.sources.celestrak",
        "orbitmind.sources.jpl",
        "orbitmind.optimization.solvers",
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
