"""API tests for the optimization-benchmark visual manifest boundary."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.routers import visual_manifests as visual_manifests_router
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import BenchmarkRun
from orbitmind.persistence.optimization_models import OptimizationArtifactRow, SolverRunRow

BASE = "/api/v1/visual-manifests/optimization-benchmark"
EXPECTED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "manifest_id",
    "read_at",
    "source_domain",
    "scope_id",
    "verified",
    "integrity_failed",
    "receipt_status",
    "comparison_conclusion",
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
    "source_labels",
    "limitations",
    "disclaimers",
    "presentation_hints",
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


def _assert_safe_manifest_text(text: str, *extra_forbidden: str) -> None:
    lowered = text.lower()
    for forbidden in (
        '"path"',
        '"sidecar_path"',
        '"quantum_evidence"',
        '"result_json"',
        '"request_json"',
        '"link_json"',
        '"samples"',
        "raw samples",
        "postgresql://",
        "sqlite://",
        "select ",
        "insert ",
        "traceback",
        ".py",
        "e:\\",
        "execution_receipt",
        "receipt envelope",
        "hmac",
        "signature",
        "signer",
        "circuit",
        "qubo",
        "provider state",
        "secret",
        *extra_forbidden,
    ):
        assert forbidden.lower() not in lowered


def _assert_safe_error(response: Any, *extra_forbidden: str) -> None:
    assert set(response.json()) == {"code", "message"}
    _assert_safe_manifest_text(response.text, *extra_forbidden)
    for forbidden in EXPECTED_TOP_LEVEL_FIELDS:
        assert forbidden not in response.text


def _assert_withheld_error(response: Any, *extra_forbidden: str) -> None:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "validation_error"
    assert "manifest withheld" in body["message"]
    assert "evidence" in body["message"]
    _assert_safe_error(response, *extra_forbidden)


def _parsed_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == UTC.utcoffset(parsed)
    return parsed


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


def test_optimization_benchmark_visual_manifest_returns_safe_response(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)

    response = client.get(f"{BASE}/{run.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == EXPECTED_TOP_LEVEL_FIELDS
    assert body["schema_version"] == "visual-manifest-v1"
    assert body["source_domain"] == "optimization-benchmark"
    assert body["scope_id"] == run.id
    assert body["manifest_id"] == f"visual-manifest:optimization-benchmark:{run.id}:v1"
    for forbidden in ("receipt", "attestation", "signature", "approval", "certification"):
        assert forbidden not in body["manifest_id"]
    _parsed_utc(body["read_at"])
    assert body["verified"] is True
    assert body["integrity_failed"] is False
    assert body["receipt_status"] == "signed"
    assert body["comparison_conclusion"] in SAFE_COMPARISON_CONCLUSIONS | {None}
    assert run.comparison is not None
    assert body["comparison_conclusion"] == run.comparison.conclusion.value
    assert "not quantum authority" in body["disclaimer"]
    assert "not a claim of general quantum advantage" in body["disclaimer"]
    assert "does not expose or repackage sidecar JSON" in " ".join(body["limitations"])
    assert "does not issue, re-sign" in " ".join(body["limitations"])

    assert body["items"]
    item_types = {item["item_type"] for item in body["items"]}
    assert item_types >= STABLE_ARTIFACT_TYPES
    for item in body["items"]:
        assert set(item) == EXPECTED_ITEM_FIELDS
        assert item["media_type"] in {"image/png", "application/json", "text/plain"}
        assert item["artifact_handle"].startswith("optimization-artifact:")
        assert item["checksum_handle"].startswith("sha256:")
        assert len(item["checksum_handle"].removeprefix("sha256:")) == 64
        assert f"optimization-benchmark:{run.id}" in item["source_record_handles"]
        assert f"optimization-problem:{run.problem_id}" in item["source_record_handles"]
        assert any(
            handle.startswith("problem-checksum:sha256:")
            for handle in item["source_record_handles"]
        )
        assert item["canonical_epistemic_status"] == "model-estimate"
        assert "evidence-authenticated:true" in item["source_labels"]
        assert "integrity-failed:false" in item["source_labels"]
        assert "receipt-status:signed" in item["source_labels"]
        assert item["presentation_hints"]["scientific_authority"] == "none-added"
        assert "artifact file authentication" in " ".join(item["limitations"])
        assert "not raw sidecar content" in " ".join(item["limitations"])
        for forbidden in (
            "path",
            "sidecar_path",
            "url",
            "quantum_evidence",
            "samples",
            "circuit",
            "qubo",
        ):
            assert forbidden not in item

    _assert_safe_manifest_text(response.text)


@pytest.mark.parametrize(
    "benchmark_id",
    [
        "not-a-uuid",
        "..escape",
        "E:%5Cquantum-project",
        "11111111222233334444555555555555",
    ],
)
def test_optimization_benchmark_visual_manifest_rejects_malformed_path_like_ids(
    client: TestClient,
    benchmark_id: str,
) -> None:
    response = client.get(f"{BASE}/{benchmark_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_optimization_benchmark_visual_manifest_missing_benchmark_returns_404(
    client: TestClient,
) -> None:
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
def test_optimization_benchmark_visual_manifest_rejects_every_query_param(
    client: TestClient,
    container: AppContainer,
    param: str,
) -> None:
    run = _create_verified_benchmark(container)

    response = client.get(f"{BASE}/{run.id}", params={param: "1"})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response)


def test_optimization_benchmark_visual_manifest_no_signer_returns_409(tmp_path: Path) -> None:
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
        response = client.get(f"{BASE}/{run.id}")

    assert response.status_code == 409
    assert response.json()["code"] == "evidence_not_authenticated"
    _assert_safe_error(response)


def test_optimization_benchmark_visual_manifest_tamper_returns_sanitized_422(
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

    response = client.get(f"{BASE}/{run.id}")

    _assert_withheld_error(response)


def test_optimization_benchmark_visual_manifest_malformed_checksum_returns_sanitized_422(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    with container.database.session() as session:
        row = session.query(OptimizationArtifactRow).filter_by(scope_id=run.id).first()
        assert row is not None
        row.checksum = "not-a-checksum"
        session.commit()

    response = client.get(f"{BASE}/{run.id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_error(response, "not-a-checksum")


def test_optimization_benchmark_visual_manifest_deleted_artifact_file_fails_closed(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    assert client.get(f"{BASE}/{run.id}").status_code == 200
    root = container.settings.resolved_artifacts_dir()
    artifact, rel = _artifact_file(root, run)
    artifact.unlink()

    response = client.get(f"{BASE}/{run.id}")

    _assert_withheld_error(response, rel, str(root))


def test_optimization_benchmark_visual_manifest_deleted_sidecar_file_fails_closed(
    client: TestClient,
    container: AppContainer,
) -> None:
    run = _create_verified_benchmark(container)
    assert client.get(f"{BASE}/{run.id}").status_code == 200
    root = container.settings.resolved_artifacts_dir()
    sidecar, rel = _sidecar_file(root, run)
    sidecar.unlink()

    response = client.get(f"{BASE}/{run.id}")

    _assert_withheld_error(response, rel, Path(rel).name, str(root))


def test_optimization_benchmark_visual_manifest_openapi_and_router_boundary(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    mission_route = "/api/v1/visual-manifests/mission/{mission_id}"
    optimization_route = "/api/v1/visual-manifests/optimization-benchmark/{benchmark_id}"
    assert mission_route in paths
    assert set(paths[mission_route]) == {"get"}
    assert optimization_route in paths
    assert set(paths[optimization_route]) == {"get"}
    visual_manifest_routes = {
        (path, method)
        for path, methods in paths.items()
        if path.startswith("/api/v1/visual-manifests")
        for method in methods
    }
    assert visual_manifest_routes == {(mission_route, "get"), (optimization_route, "get")}

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
