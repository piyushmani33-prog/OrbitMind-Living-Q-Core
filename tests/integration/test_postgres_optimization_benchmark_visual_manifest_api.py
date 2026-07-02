"""Live PostgreSQL API tests for the optimization-benchmark visual manifest route.

Skips unless ORBITMIND_TEST_POSTGRES_URL points at a disposable migrated database.
These tests do not call create_all(); they validate the HTTP manifest boundary
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

BASE = "/api/v1/visual-manifests/optimization-benchmark"
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
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
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
        '"quantum_evidence"',
        '"result_json"',
        '"request_json"',
        '"link_json"',
        '"samples"',
        "postgresql://",
        "select ",
        "insert ",
        "traceback",
        ".py",
        "e:\\",
        "hmac",
        "signature",
        "signer",
        "circuit",
        "qubo",
        "provider state",
        *extra_forbidden,
    ):
        assert forbidden not in lowered


def _assert_withheld_error(response: Any, *extra_forbidden: str) -> None:
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "validation_error"
    assert "manifest withheld" in body["message"]
    assert "evidence" in body["message"]
    for field in (
        "schema_version",
        "manifest_id",
        "items",
        "verified",
        "receipt_status",
        "comparison_conclusion",
    ):
        assert field not in response.text
    _assert_safe_text(response.text, *extra_forbidden)


def test_postgres_optimization_benchmark_visual_manifest_http_boundary(
    pg_client: TestClient,
    pg_container: AppContainer,
) -> None:
    run = _create_benchmark(pg_container)
    benchmark_id = run.id

    success = pg_client.get(f"{BASE}/{benchmark_id}")
    invalid = pg_client.get(f"{BASE}/not-a-uuid")
    missing = pg_client.get(f"{BASE}/11111111-2222-3333-4444-555555555555")
    query = pg_client.get(f"{BASE}/{benchmark_id}", params={"owner_id": "spoof"})

    assert success.status_code == 200, success.text
    body = success.json()
    assert body["schema_version"] == "visual-manifest-v1"
    assert body["source_domain"] == "optimization-benchmark"
    assert body["scope_id"] == benchmark_id
    assert body["manifest_id"] == f"visual-manifest:optimization-benchmark:{benchmark_id}:v1"
    assert body["verified"] is True
    assert body["integrity_failed"] is False
    assert body["receipt_status"] == "signed"
    artifact_types = {item["item_type"] for item in body["items"]}
    assert artifact_types >= {
        "selected_observation_timeline",
        "solver_objective_comparison",
        "feasibility_violation_comparison",
        "benchmark_summary_json",
    }
    for item in body["items"]:
        assert item["artifact_handle"].startswith("optimization-artifact:")
        assert item["checksum_handle"].startswith("sha256:")
        assert f"optimization-benchmark:{benchmark_id}" in item["source_record_handles"]
        assert item["canonical_epistemic_status"] == "model-estimate"
        assert "path" not in item
        assert "sidecar_path" not in item
    _assert_safe_text(success.text)

    assert invalid.status_code == 422
    assert missing.status_code == 404
    assert query.status_code == 422
    for response in (invalid, missing, query):
        assert set(response.json()) == {"code", "message"}
        _assert_safe_text(response.text)


def test_postgres_optimization_benchmark_visual_manifest_checksum_tamper_is_422(
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

    response = pg_client.get(f"{BASE}/{benchmark_id}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    _assert_safe_text(response.text)


@pytest.mark.parametrize("delete_target", ["artifact", "sidecar"])
def test_postgres_optimization_benchmark_visual_manifest_file_absence_is_422(
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

    response = pg_client.get(f"{BASE}/{run.id}")

    _assert_withheld_error(response, rel, target.name, str(root))
