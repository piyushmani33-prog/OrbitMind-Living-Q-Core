"""API tests for the optimization-benchmark static report boundary."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.routers import static_reports as static_reports_router
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import BenchmarkRun
from orbitmind.optimization.service import OptimizationService
from orbitmind.persistence.optimization_models import OptimizationArtifactRow, SolverRunRow
from orbitmind.visualization.optimization_charts import OptimizationVisualizationService

BASE = "/api/v1/static-reports/optimization-benchmark"
VISUAL_MANIFEST_BASE = "/api/v1/visual-manifests/optimization-benchmark"
MISSION_STATIC_REPORT_BASE = "/api/v1/static-reports/mission"
MISSION_ENDPOINT = "/api/v1/missions/orbit-propagation"
EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "report_id",
    "read_at",
    "source_domain",
    "scope_id",
    "report_status",
    "inputs_and_provenance",
    "optimization_benchmark_summary",
    "evidence_and_limitations",
    "appendix",
    "limitations",
    "disclaimer",
}
EXPECTED_STATUS_FIELDS = {
    "report_kind",
    "generation_mode",
    "authority",
    "authentication_mode",
    "failure_mode",
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
    "benchmark_id",
    "verified",
    "integrity_failed",
    "receipt_status",
    "comparison_conclusion",
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
    "receipt_status",
    "delegated_authentication",
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
STABLE_ARTIFACT_TYPES = {
    "selected_observation_timeline",
    "solver_objective_comparison",
    "feasibility_violation_comparison",
    "benchmark_summary_json",
}
SAFE_COMPARISON_CONCLUSIONS = {
    "quantum-competitive",
    "quantum-worse",
    "equivalent-objective",
    "classical-exact-best",
    "insufficient-evidence",
}


def _create_verified_benchmark(container: AppContainer) -> BenchmarkRun:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _findings = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    auth = container.optimization_service.read_benchmark_evidence(run.id)
    assert auth.authenticated and not auth.integrity_failed
    return run


def _create_mission(client: TestClient, iss_request: dict[str, object]) -> str:
    response = client.post(MISSION_ENDPOINT, json=iss_request)
    assert response.status_code == 201, response.text
    return str(response.json()["mission_id"])


def _artifact_file(root: Path, run: BenchmarkRun) -> tuple[Path, str]:
    rel = str(run.artifacts[0]["path"])
    path = root / rel
    assert path.is_file()
    return path, rel


def _sidecar_file(root: Path, run: BenchmarkRun) -> tuple[Path, str]:
    rel = f"{run.artifacts[0]['path']}.json"
    path = root / rel
    assert path.is_file()
    return path, rel


def _assert_safe_report_text(text: str, *extra_forbidden: str) -> None:
    lowered = text.lower()
    for forbidden in (
        '"path"',
        '"sidecar_path"',
        '"url"',
        '"quantum_evidence"',
        '"result_json"',
        '"request_json"',
        '"link_json"',
        '"samples"',
        "raw samples",
        "raw sidecar json",
        "postgresql://",
        "sqlite://",
        "select ",
        "insert ",
        "traceback",
        ".py",
        "e:\\",
        "execution_receipt",
        "receipt envelope",
        "canonical receipt",
        "hmac",
        "signature",
        "signer",
        "payload",
        "key material",
        "circuit",
        "qubo",
        "solver internals",
        "provider state",
        "secret",
        *extra_forbidden,
    ):
        assert forbidden.lower() not in lowered


def _assert_safe_error(response: Any, *extra_forbidden: str) -> None:
    assert set(response.json()) == {"code", "message"}
    _assert_safe_report_text(response.text, *extra_forbidden)
    for forbidden in EXPECTED_TOP_LEVEL_FIELDS:
        assert forbidden not in response.text


def _assert_withheld_error(response: Any, *extra_forbidden: str) -> None:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "validation_error"
    assert "report withheld" in body["message"]
    assert "evidence" in body["message"]
    _assert_safe_error(response, *extra_forbidden)


def _parsed_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == UTC.utcoffset(parsed)
    return parsed


def test_optimization_benchmark_static_report_returns_safe_json_report(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)

    response = client.get(f"{BASE}/{run.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_TOP_LEVEL_FIELDS
    assert body["schema_version"] == "static-report-v1"
    assert body["source_domain"] == "optimization-benchmark"
    assert body["scope_id"] == run.id
    assert body["report_id"] == f"static-report:optimization-benchmark:{run.id}:v1"
    for forbidden in ("certificate", "attestation", "approval", "receipt", "signature"):
        assert forbidden not in body["report_id"]
    _parsed_utc(body["read_at"])

    assert set(body["report_status"]) == EXPECTED_STATUS_FIELDS
    assert body["report_status"]["report_kind"] == "optimization-benchmark-static-report"
    assert body["report_status"]["generation_mode"] == "on-demand"
    assert body["report_status"]["authority"] == "non-authoritative"
    assert body["report_status"]["authentication_mode"] == "delegated-read-authentication"
    assert body["report_status"]["failure_mode"] == "fail-closed"
    assert "non-authoritative" in body["report_status"]["report_id_status"]
    assert "not currently owner-scoped" in body["report_status"]["owner_scope"]

    assert set(body["inputs_and_provenance"]) == EXPECTED_INPUT_FIELDS
    assert body["inputs_and_provenance"]["manifest_id"] == (
        f"visual-manifest:optimization-benchmark:{run.id}:v1"
    )
    assert body["inputs_and_provenance"]["manifest_schema_version"] == "visual-manifest-v1"
    assert body["inputs_and_provenance"]["manifest_source_domain"] == "optimization-benchmark"
    assert body["inputs_and_provenance"]["manifest_scope_id"] == run.id
    assert (
        f"optimization-benchmark:{run.id}" in body["inputs_and_provenance"]["source_record_handles"]
    )
    assert (
        f"optimization-problem:{run.problem_id}"
        in body["inputs_and_provenance"]["source_record_handles"]
    )

    summary = body["optimization_benchmark_summary"]
    assert set(summary) == EXPECTED_SUMMARY_FIELDS
    assert summary["benchmark_id"] == run.id
    assert summary["verified"] is True
    assert summary["integrity_failed"] is False
    assert summary["receipt_status"] == "signed"
    assert summary["comparison_conclusion"] in SAFE_COMPARISON_CONCLUSIONS | {None}
    assert run.comparison is not None
    assert summary["comparison_conclusion"] == run.comparison.conclusion.value
    assert set(summary["artifact_types"]) >= STABLE_ARTIFACT_TYPES
    assert summary["artifact_count"] == len(summary["artifact_handles"])
    assert all(
        handle.startswith("optimization-artifact:") for handle in summary["artifact_handles"]
    )
    assert all(handle.startswith("sha256:") for handle in summary["checksum_handles"])
    assert "receipt-status:signed" in summary["source_labels"]
    assert "evidence-authenticated:true" in summary["source_labels"]
    assert "integrity-failed:false" in summary["source_labels"]

    evidence = body["evidence_and_limitations"]
    assert set(evidence) == EXPECTED_EVIDENCE_FIELDS
    assert evidence["evidence_status"] == "authenticated"
    assert evidence["withheld"] is False
    assert evidence["receipt_status"] == "signed"
    assert "benchmark read-authentication" in evidence["delegated_authentication"]
    for boundary in (
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
        assert boundary in evidence["authority_boundaries"]
    assert "not proof by itself" in body["disclaimer"]
    assert "not evidence by itself" in body["disclaimer"]
    assert "not signed receipt authority" in body["disclaimer"]
    assert "not quantum authority" in body["disclaimer"]
    assert "not a claim of general quantum advantage" in body["disclaimer"]

    assert set(body["appendix"]) == EXPECTED_APPENDIX_FIELDS
    assert body["appendix"]["route_references"] == [
        "GET /api/v1/static-reports/optimization-benchmark/{benchmark_id}",
        "GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}",
    ]
    assert body["appendix"]["manifest_reference"] == (
        f"visual-manifest:optimization-benchmark:{run.id}:v1"
    )
    assert body["appendix"]["artifact_handles"] == summary["artifact_handles"]
    assert body["appendix"]["checksum_handles"] == summary["checksum_handles"]

    limitations = " ".join(body["limitations"])
    assert "not persisted as a report artifact" in limitations
    assert "fails closed" in limitations
    assert "does not parse, expose, or repackage sidecar JSON" in limitations
    assert "diagnostic only" in limitations
    assert "classical-baseline-authoritative" in limitations
    _assert_safe_report_text(response.text)


@pytest.mark.parametrize(
    "benchmark_id",
    [
        "not-a-uuid",
        "..escape",
        "E:%5Cquantum-project",
        "11111111222233334444555555555555",
    ],
)
def test_optimization_benchmark_static_report_rejects_malformed_path_like_ids(
    client: TestClient,
    benchmark_id: str,
) -> None:
    response = client.get(f"{BASE}/{benchmark_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_optimization_benchmark_static_report_missing_benchmark_returns_404(
    client: TestClient,
) -> None:
    missing_id = "11111111-2222-3333-4444-555555555555"

    report = client.get(f"{BASE}/{missing_id}")
    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{missing_id}")

    assert report.status_code == 404
    assert manifest.status_code == report.status_code
    assert report.json()["code"] == "not_found"
    _assert_safe_error(report)


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
def test_optimization_benchmark_static_report_rejects_every_query_param(
    client: TestClient,
    container: AppContainer,
    param: str,
) -> None:
    run = _create_verified_benchmark(container)

    response = client.get(f"{BASE}/{run.id}", params={param: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_optimization_benchmark_static_report_no_signer_returns_409(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'unsigned.db').as_posix()}",
        artifacts_dir=tmp_path / "unsigned-artifacts",
        env="test",
        evidence_signing_key="",
    )
    unsigned_container = AppContainer(settings=settings)
    unsigned_container.init_storage()
    problem = unsigned_container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _findings = unsigned_container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )

    with TestClient(create_app(unsigned_container), raise_server_exceptions=False) as client:
        report = client.get(f"{BASE}/{run.id}")
        manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")

    assert report.status_code == 409
    assert manifest.status_code == report.status_code
    assert report.json()["code"] == "evidence_not_authenticated"
    _assert_safe_error(report)


def test_optimization_benchmark_static_report_tamper_returns_sanitized_422(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    with container.database.session() as session:
        row = (
            session.query(SolverRunRow)
            .filter(SolverRunRow.benchmark_id == run.id, SolverRunRow.solver_kind == "exact")
            .first()
        )
        assert row is not None
        blob = dict(row.result_json)
        blob["objective_value"] = 999.0
        row.result_json = blob
        session.commit()

    report = client.get(f"{BASE}/{run.id}")
    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")

    assert manifest.status_code == report.status_code
    _assert_withheld_error(report)


def test_optimization_benchmark_static_report_malformed_checksum_returns_sanitized_422(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    with container.database.session() as session:
        row = session.query(OptimizationArtifactRow).filter_by(scope_id=run.id).first()
        assert row is not None
        row.checksum = "not-a-checksum"
        session.commit()

    report = client.get(f"{BASE}/{run.id}")
    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")

    assert manifest.status_code == report.status_code
    assert report.status_code == 422
    assert report.json()["code"] == "validation_error"
    _assert_safe_error(report, "not-a-checksum")


def test_optimization_benchmark_static_report_deleted_artifact_file_fails_closed(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    assert client.get(f"{BASE}/{run.id}").status_code == 200
    root = container.settings.resolved_artifacts_dir()
    artifact, rel = _artifact_file(root, run)
    artifact.unlink()

    report = client.get(f"{BASE}/{run.id}")
    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")

    assert manifest.status_code == report.status_code
    _assert_withheld_error(report, rel, str(root))


def test_optimization_benchmark_static_report_deleted_sidecar_file_fails_closed(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    assert client.get(f"{BASE}/{run.id}").status_code == 200
    root = container.settings.resolved_artifacts_dir()
    sidecar, rel = _sidecar_file(root, run)
    sidecar.unlink()

    report = client.get(f"{BASE}/{run.id}")
    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")

    assert manifest.status_code == report.status_code
    _assert_withheld_error(report, rel, Path(rel).name, str(root))


def test_optimization_benchmark_static_report_does_not_regenerate_or_fetch(
    client: TestClient,
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _create_verified_benchmark(container)

    def fail(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unexpected regeneration, benchmark rerun, or provider fetch")

    monkeypatch.setattr(OptimizationVisualizationService, "generate", fail)
    monkeypatch.setattr(OptimizationService, "benchmark", fail)

    response = client.get(f"{BASE}/{run.id}")

    assert response.status_code == 200, response.text
    assert response.json()["scope_id"] == run.id


def test_optimization_benchmark_static_report_is_deterministic_except_read_at(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)

    first = client.get(f"{BASE}/{run.id}")
    second = client.get(f"{BASE}/{run.id}")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_body = first.json()
    second_body = second.json()
    first_body["read_at"] = "<utc-read-time>"
    second_body["read_at"] = "<utc-read-time>"
    assert first_body == second_body


def test_optimization_benchmark_static_report_matches_live_visual_manifest_projection(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)

    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")
    report = client.get(f"{BASE}/{run.id}")

    assert manifest.status_code == 200, manifest.text
    assert report.status_code == 200, report.text
    manifest_body = manifest.json()
    report_body = report.json()
    summary = report_body["optimization_benchmark_summary"]
    manifest_handles = [item["artifact_handle"] for item in manifest_body["items"]]
    manifest_checksums = [item["checksum_handle"] for item in manifest_body["items"]]
    assert report_body["inputs_and_provenance"]["manifest_id"] == manifest_body["manifest_id"]
    assert report_body["appendix"]["manifest_reference"] == manifest_body["manifest_id"]
    assert summary["artifact_handles"] == manifest_handles
    assert summary["checksum_handles"] == manifest_checksums
    assert summary["comparison_conclusion"] == manifest_body["comparison_conclusion"]
    assert summary["verified"] == manifest_body["verified"]
    assert summary["integrity_failed"] == manifest_body["integrity_failed"]
    assert summary["receipt_status"] == manifest_body["receipt_status"]


def test_optimization_benchmark_static_report_shape_is_distinct(
    client: TestClient,
    container: AppContainer,
    iss_request: dict[str, object],
) -> None:
    run = _create_verified_benchmark(container)
    mission_id = _create_mission(client, iss_request)

    manifest = client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}").json()
    optimization_report = client.get(f"{BASE}/{run.id}").json()
    mission_report = client.get(f"{MISSION_STATIC_REPORT_BASE}/{mission_id}").json()

    assert set(optimization_report) == EXPECTED_TOP_LEVEL_FIELDS
    assert set(optimization_report) != set(manifest)
    assert set(optimization_report) != set(mission_report)
    assert "items" not in optimization_report
    assert "optimization_benchmark_summary" in optimization_report
    assert "mission_summary" not in optimization_report


def test_optimization_benchmark_static_report_openapi_and_router_boundary(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    mission_route = "/api/v1/static-reports/mission/{mission_id}"
    optimization_route = "/api/v1/static-reports/optimization-benchmark/{benchmark_id}"
    assert mission_route in paths
    assert set(paths[mission_route]) == {"get"}
    assert optimization_route in paths
    assert set(paths[optimization_route]) == {"get"}
    static_report_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith("/api/v1/static-reports")
        for method in methods
    }
    assert static_report_routes == {(mission_route, "get"), (optimization_route, "get")}
    assert "/api/v1/static-reports/{domain}/{scope_id}" not in paths

    router_source = Path(static_reports_router.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "orbitmind.visualization.charts",
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
