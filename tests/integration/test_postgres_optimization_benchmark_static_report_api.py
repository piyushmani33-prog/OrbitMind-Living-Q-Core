"""Live PostgreSQL API tests for the optimization-benchmark static report route.

Skips unless ORBITMIND_TEST_POSTGRES_URL points at a disposable migrated database.
These tests do not call create_all(); they validate the HTTP report boundary
against the migrated schema.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.signing_fixtures import TEST_ONLY_EVIDENCE_SIGNING_MATERIAL

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import BenchmarkRun

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

BASE = "/api/v1/static-reports/optimization-benchmark"
VISUAL_MANIFEST_BASE = "/api/v1/visual-manifests/optimization-benchmark"
_TABLES = (
    "optimization_artifacts",
    "benchmark_execution_receipts",
    "benchmark_comparisons",
    "quantum_sample_results",
    "quantum_experiments",
    "solver_runs",
    "benchmark_runs",
    "scheduling_constraints",
    "observation_opportunities",
    "optimization_problems",
    "memory_graph_edges",
    "audit_events",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> Iterator[AppContainer]:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key=TEST_ONLY_EVIDENCE_SIGNING_MATERIAL,
    )
    container = AppContainer(settings=settings)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield container
    container.database.engine.dispose()


@pytest.fixture
def pg_client(pg_container: AppContainer) -> Iterator[TestClient]:
    with TestClient(create_app(pg_container), raise_server_exceptions=False) as client:
        yield client


def _create_benchmark(container: AppContainer) -> BenchmarkRun:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _findings = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    auth = container.optimization_service.read_benchmark_evidence(run.id)
    assert auth.authenticated and not auth.integrity_failed
    return run


def _assert_safe_text(text_value: str, *extra_forbidden: str) -> None:
    lowered = text_value.lower()
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
        "postgresql://",
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
        "circuit",
        "qubo",
        "solver internals",
        "provider state",
        *extra_forbidden,
    ):
        assert forbidden not in lowered


def _assert_safe_error(response: Any, *extra_forbidden: str) -> None:
    assert set(response.json()) == {"code", "message"}
    _assert_safe_text(response.text, *extra_forbidden)
    for field in (
        "schema_version",
        "report_id",
        "optimization_benchmark_summary",
        "evidence_and_limitations",
        "receipt_status",
        "comparison_conclusion",
    ):
        assert field not in response.text


def _assert_withheld_error(response: Any, *extra_forbidden: str) -> None:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "validation_error"
    assert "report withheld" in body["message"]
    assert "evidence" in body["message"]
    _assert_safe_error(response, *extra_forbidden)


def test_postgres_optimization_benchmark_static_report_http_boundary(
    pg_client: TestClient,
    pg_container: AppContainer,
) -> None:
    run = _create_benchmark(pg_container)
    benchmark_id = run.id

    success = pg_client.get(f"{BASE}/{benchmark_id}")
    invalid = pg_client.get(f"{BASE}/not-a-uuid")
    missing = pg_client.get(f"{BASE}/11111111-2222-3333-4444-555555555555")
    query = pg_client.get(f"{BASE}/{benchmark_id}", params={"owner_id": "spoof"})
    missing_manifest = pg_client.get(f"{VISUAL_MANIFEST_BASE}/11111111-2222-3333-4444-555555555555")

    assert success.status_code == 200, success.text
    body = success.json()
    assert body["schema_version"] == "static-report-v1"
    assert body["source_domain"] == "optimization-benchmark"
    assert body["scope_id"] == benchmark_id
    assert body["report_id"] == f"static-report:optimization-benchmark:{benchmark_id}:v1"
    assert body["inputs_and_provenance"]["manifest_id"] == (
        f"visual-manifest:optimization-benchmark:{benchmark_id}:v1"
    )
    summary = body["optimization_benchmark_summary"]
    assert summary["verified"] is True
    assert summary["integrity_failed"] is False
    assert summary["receipt_status"] == "signed"
    assert set(summary["artifact_types"]) >= {
        "selected_observation_timeline",
        "solver_objective_comparison",
        "feasibility_violation_comparison",
        "benchmark_summary_json",
    }
    assert body["evidence_and_limitations"]["withheld"] is False
    assert "not proof by itself" in body["disclaimer"]
    assert "not signed receipt authority" in body["disclaimer"]
    _assert_safe_text(success.text)

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert missing_manifest.status_code == missing.status_code
    assert query.status_code == 422
    for response in (invalid, missing, query):
        _assert_safe_error(response)


def test_postgres_optimization_benchmark_static_report_checksum_tamper_is_422(
    pg_client: TestClient,
    pg_container: AppContainer,
) -> None:
    run = _create_benchmark(pg_container)
    benchmark_id = run.id
    with pg_container.database.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE optimization_artifacts SET checksum='not-a-checksum' WHERE scope_id=:scope"
            ),
            {"scope": benchmark_id},
        )

    report = pg_client.get(f"{BASE}/{benchmark_id}")
    manifest = pg_client.get(f"{VISUAL_MANIFEST_BASE}/{benchmark_id}")

    assert manifest.status_code == report.status_code
    assert report.status_code == 422
    assert report.json()["code"] == "validation_error"
    _assert_safe_error(report, "not-a-checksum")


@pytest.mark.parametrize("delete_target", ["artifact", "sidecar"])
def test_postgres_optimization_benchmark_static_report_file_absence_is_422(
    pg_client: TestClient,
    pg_container: AppContainer,
    delete_target: str,
) -> None:
    run = _create_benchmark(pg_container)
    clean = pg_client.get(f"{BASE}/{run.id}")
    assert clean.status_code == 200, clean.text

    root = pg_container.settings.resolved_artifacts_dir()
    rel = str(run.artifacts[0]["path"])
    if delete_target == "sidecar":
        rel = f"{rel}.json"
    target = root / rel
    assert target.is_file()
    target.unlink()

    report = pg_client.get(f"{BASE}/{run.id}")
    manifest = pg_client.get(f"{VISUAL_MANIFEST_BASE}/{run.id}")

    assert manifest.status_code == report.status_code
    _assert_withheld_error(report, rel, target.name, str(root))
