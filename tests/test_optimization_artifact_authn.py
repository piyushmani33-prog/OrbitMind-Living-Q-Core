"""Unauthenticated artifacts are not served as ordinary evidence (fifth review, Medium #2)."""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from tests.test_optimization_read_auth import _tamper_exact_objective


@pytest.fixture
def signed_client(container: AppContainer):
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    with TestClient(create_app(container)) as client:
        yield client, container


def test_valid_authenticated_benchmark_serves_artifacts(signed_client) -> None:
    client, container = signed_client
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    resp = client.get(f"/api/v1/optimization/runs/{run.id}/artifacts")
    assert resp.status_code == 200 and resp.json()["artifacts"]


def test_tampered_benchmark_artifacts_withheld_422(signed_client) -> None:
    client, container = signed_client
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    _tamper_exact_objective(container, run.id)
    assert client.get(f"/api/v1/optimization/runs/{run.id}/artifacts").status_code == 422


def test_no_signer_benchmark_artifacts_not_authenticated_409(tmp_path) -> None:
    # A container with NO signer never accepts evidence; its artifacts are diagnostic only (409).
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'nosig.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        env="test",  # NO evidence_signing_key -> no-signer mode
    )
    container = AppContainer(settings=settings)
    container.init_storage()
    with TestClient(create_app(container)) as client:
        problem = container.optimization_service.create_problem(fixtures.fixture("default"))
        run, findings = container.optimization_service.benchmark(
            problem.id, seed=7, run_quantum=False, generate_artifacts=True
        )
        # Unaccepted (no execution provenance).
        receipt_finding = next(f for f in findings if f.check_id == "opt.execution_receipt")
        assert not receipt_finding.passed
        resp = client.get(f"/api/v1/optimization/runs/{run.id}/artifacts")
        assert resp.status_code == 409
        assert resp.json()["code"] == "evidence_not_authenticated"
