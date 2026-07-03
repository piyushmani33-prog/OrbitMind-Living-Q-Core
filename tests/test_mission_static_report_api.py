"""API tests for the mission static report boundary."""

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
from orbitmind.api.routers import static_reports as static_reports_router
from orbitmind.persistence.models import ArtifactRow

BASE = "/api/v1/static-reports/mission"
MISSION_ENDPOINT = "/api/v1/missions/orbit-propagation"
VISUAL_MANIFEST_BASE = "/api/v1/visual-manifests/mission"
EXPECTED_TOP_LEVEL_FIELDS = {
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
EXPECTED_STATUS_FIELDS = {
    "report_kind",
    "generation_mode",
    "authority",
    "report_id_status",
    "owner_scope",
}
EXPECTED_INPUT_FIELDS = {
    "manifest_id",
    "manifest_schema_version",
    "manifest_source_domain",
    "manifest_scope_id",
    "source_record_handles",
    "checksum_handles",
    "source_labels",
}
EXPECTED_SUMMARY_FIELDS = {
    "mission_id",
    "epistemic_status",
    "verification_state",
    "artifact_count",
    "artifact_types",
    "artifact_handles",
    "checksum_handles",
    "source_labels",
    "limitations",
}
EXPECTED_EVIDENCE_FIELDS = {
    "evidence_status",
    "withheld",
    "authority_boundaries",
    "limitations",
    "disclaimer",
}
EXPECTED_APPENDIX_FIELDS = {
    "route_references",
    "manifest_reference",
    "source_record_handles",
    "artifact_handles",
    "checksum_handles",
}


def _create_mission(client: TestClient, iss_request: dict[str, object]) -> str:
    response = client.post(MISSION_ENDPOINT, json=iss_request)
    assert response.status_code == 201, response.text
    return str(response.json()["mission_id"])


def _assert_safe_report_text(text: str) -> None:
    forbidden = (
        '"path"',
        '"sidecar_path"',
        '"url"',
        '"artifact_type"',
        "source_references",
        "tle_line1",
        "tle_line2",
        "raw tle",
        "raw samples",
        "raw intervals",
        "result_json",
        "request_json",
        "link_json",
        "postgresql://",
        "select ",
        "insert ",
        "traceback",
        ".py",
        "e:\\",
        "execution_receipt",
        '"signature"',
        "hmac",
        "quantum_evidence",
        "qubo",
        "provider state",
    )
    lowered = text.lower()
    for term in forbidden:
        assert term not in lowered


def _assert_safe_error(response: Any) -> None:
    assert set(response.json()) == {"code", "message"}
    _assert_safe_report_text(response.text)
    for forbidden in ("constraint", "artifact_records", "sidecar", "not-a-checksum"):
        assert forbidden not in response.text.lower()


def _parsed_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() is not None
    return parsed


def test_mission_static_report_returns_safe_json_report(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_TOP_LEVEL_FIELDS
    assert body["schema_version"] == "static-report-v1"
    assert body["source_domain"] == "mission"
    assert body["scope_id"] == mission_id
    assert body["report_id"] == f"static-report:mission:{mission_id}:v1"
    for forbidden in ("certificate", "attestation", "approval", "receipt", "signature"):
        assert forbidden not in body["report_id"]
    _parsed_utc(body["read_at"])

    assert set(body["report_status"]) == EXPECTED_STATUS_FIELDS
    assert body["report_status"]["report_kind"] == "mission-static-report"
    assert body["report_status"]["generation_mode"] == "on-demand"
    assert body["report_status"]["authority"] == "non-authoritative"
    assert "non-authoritative" in body["report_status"]["report_id_status"]
    assert "not currently owner-scoped" in body["report_status"]["owner_scope"]

    assert set(body["inputs_and_provenance"]) == EXPECTED_INPUT_FIELDS
    assert body["inputs_and_provenance"]["manifest_id"] == (
        f"visual-manifest:mission:{mission_id}:v1"
    )
    assert body["inputs_and_provenance"]["manifest_schema_version"] == "visual-manifest-v1"
    assert body["inputs_and_provenance"]["manifest_source_domain"] == "mission"
    assert body["inputs_and_provenance"]["manifest_scope_id"] == mission_id
    assert body["inputs_and_provenance"]["source_record_handles"][0] == f"mission:{mission_id}"
    assert len(body["inputs_and_provenance"]["checksum_handles"]) == 2

    assert set(body["mission_summary"]) == EXPECTED_SUMMARY_FIELDS
    assert body["mission_summary"]["mission_id"] == mission_id
    assert body["mission_summary"]["epistemic_status"] == "deterministic-calculation"
    assert body["mission_summary"]["verification_state"] == "mission-verification-passed"
    assert body["mission_summary"]["artifact_count"] == 2
    assert set(body["mission_summary"]["artifact_types"]) == {"altitude_vs_time", "ground_track"}
    assert all(
        handle.startswith("mission-artifact:")
        for handle in body["mission_summary"]["artifact_handles"]
    )
    assert all(
        handle.startswith("sha256:") for handle in body["mission_summary"]["checksum_handles"]
    )

    assert set(body["evidence_and_limitations"]) == EXPECTED_EVIDENCE_FIELDS
    assert body["evidence_and_limitations"]["evidence_status"] == "available"
    assert body["evidence_and_limitations"]["withheld"] is False
    for boundary in (
        "no live tracking",
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
        assert boundary in body["evidence_and_limitations"]["authority_boundaries"]
    assert "not proof by itself" in body["disclaimer"]
    assert "not evidence by itself" in body["disclaimer"]

    assert set(body["appendix"]) == EXPECTED_APPENDIX_FIELDS
    assert body["appendix"]["route_references"] == [
        "GET /api/v1/static-reports/mission/{mission_id}",
        "GET /api/v1/visual-manifests/mission/{mission_id}",
    ]
    assert body["appendix"]["manifest_reference"] == f"visual-manifest:mission:{mission_id}:v1"
    assert body["appendix"]["artifact_handles"] == body["mission_summary"]["artifact_handles"]
    assert body["appendix"]["checksum_handles"] == body["mission_summary"]["checksum_handles"]

    assert "not persisted as a report artifact" in " ".join(body["limitations"])
    assert "does not inspect image bytes" in " ".join(body["limitations"])
    assert "not approval" in body["disclaimer"]
    assert "not certification" in body["disclaimer"]
    assert "not signed receipt authority" in body["disclaimer"]
    _assert_safe_report_text(response.text)


@pytest.mark.parametrize(
    "mission_id",
    [
        "not-a-uuid",
        "..escape",
        "E:%5Cquantum-project",
        "11111111222233334444555555555555",
    ],
)
def test_mission_static_report_rejects_malformed_path_like_ids(
    client: TestClient,
    mission_id: str,
) -> None:
    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_static_report_missing_mission_returns_404(client: TestClient) -> None:
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
def test_mission_static_report_rejects_every_query_param(
    client: TestClient,
    iss_request: dict[str, object],
    param: str,
) -> None:
    mission_id = _create_mission(client, iss_request)

    response = client.get(f"{BASE}/{mission_id}", params={param: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_mission_static_report_does_not_need_sidecar_or_png_files(
    client: TestClient,
    container: AppContainer,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)
    shutil.rmtree(container.settings.resolved_artifacts_dir())

    response = client.get(f"{BASE}/{mission_id}")

    assert response.status_code == 200, response.text
    assert response.json()["scope_id"] == mission_id
    _assert_safe_report_text(response.text)


def test_mission_static_report_does_not_recompute_regenerate_or_fetch(
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


def test_mission_static_report_malformed_persisted_checksum_is_sanitized_422(
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


def test_mission_static_report_is_deterministic_except_read_at(
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


def test_mission_static_report_matches_live_visual_manifest_projection(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{mission_id}")
    report = client.get(f"{BASE}/{mission_id}")

    assert manifest.status_code == 200, manifest.text
    assert report.status_code == 200, report.text
    manifest_body = manifest.json()
    report_body = report.json()
    manifest_handles = [item["artifact_handle"] for item in manifest_body["items"]]
    manifest_checksums = [item["checksum_handle"] for item in manifest_body["items"]]
    assert report_body["inputs_and_provenance"]["manifest_id"] == manifest_body["manifest_id"]
    assert report_body["appendix"]["manifest_reference"] == manifest_body["manifest_id"]
    assert report_body["mission_summary"]["artifact_handles"] == manifest_handles
    assert report_body["mission_summary"]["checksum_handles"] == manifest_checksums


def test_mission_static_report_shape_differs_from_visual_manifest(
    client: TestClient,
    iss_request: dict[str, object],
) -> None:
    mission_id = _create_mission(client, iss_request)

    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{mission_id}").json()
    report = client.get(f"{BASE}/{mission_id}").json()

    assert set(report) == EXPECTED_TOP_LEVEL_FIELDS
    assert set(report) != set(manifest)
    assert "items" not in report
    assert "mission_summary" in report


def test_mission_static_report_openapi_and_router_boundary(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    route = "/api/v1/static-reports/mission/{mission_id}"
    assert route in paths
    assert set(paths[route]) == {"get"}
    static_report_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith("/api/v1/static-reports")
        for method in methods
    }
    assert static_report_routes == {(route, "get")}
    assert "/api/v1/static-reports/{domain}/{scope_id}" not in paths

    router_source = Path(static_reports_router.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "orbitmind.visualization",
        "orbitmind.space.propagation",
        "orbitmind.sources.celestrak",
        "orbitmind.sources.jpl",
        "orbitmind.optimization.solvers",
        "orbitmind.quantum",
        "qiskit",
        "frontend",
        "dashboard",
        "report_export",
        "report.export",
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
