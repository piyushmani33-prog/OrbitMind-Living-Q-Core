"""Read-time re-authentication of persisted benchmark evidence (fourth review, Critical #2)."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_models import (
    BenchmarkComparisonRow,
    BenchmarkExecutionReceiptRow,
    BenchmarkRunRow,
    SolverRunRow,
)
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository


def _accepted_benchmark(container: AppContainer) -> str:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    # Sanity: it was genuinely accepted at write time.
    session = container.database.session()
    accepted = SqlAlchemyOptimizationRepository(session).get_benchmark(run.id)
    session.close()
    assert accepted is not None and accepted.verification_passed is True
    return run.id


def test_untampered_benchmark_reauthenticates(container: AppContainer) -> None:
    bid = _accepted_benchmark(container)
    auth = container.optimization_service.read_benchmark_evidence(bid)
    assert auth.found and auth.authenticated and not auth.integrity_failed
    assert auth.receipt_status == "signed"


def _tamper_exact_objective(container: AppContainer, bid: str) -> None:
    session = container.database.session()
    row = (
        session.query(SolverRunRow)
        .filter(SolverRunRow.benchmark_id == bid, SolverRunRow.solver_kind == "exact")
        .first()
    )
    blob = dict(row.result_json)
    blob["objective_value"] = 999.0
    row.result_json = blob
    session.commit()
    session.close()


def _tamper_receipt_signature(container: AppContainer, bid: str) -> None:
    session = container.database.session()
    row = session.query(BenchmarkExecutionReceiptRow).filter_by(benchmark_id=bid).first()
    row.signature = "00" * 32
    session.commit()
    session.close()


def _tamper_receipt_payload(container: AppContainer, bid: str) -> None:
    session = container.database.session()
    row = session.query(BenchmarkExecutionReceiptRow).filter_by(benchmark_id=bid).first()
    payload = dict(row.payload_json)
    payload["problem_checksum"] = "forged"
    row.payload_json = payload
    session.commit()
    session.close()


def _tamper_comparison_conclusion(container: AppContainer, bid: str) -> None:
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    row.conclusion = "quantum-competitive"
    session.commit()
    session.close()


def _tamper_policy_snapshot(container: AppContainer, bid: str) -> None:
    session = container.database.session()
    row = session.get(BenchmarkRunRow, bid)
    snap = dict(row.policy_snapshot_json)
    snap["competitive_relative_gap"] = 0.9
    row.policy_snapshot_json = snap
    session.commit()
    session.close()


_TAMPERS: list[tuple[str, Callable[[AppContainer, str], None]]] = [
    ("exact_objective", _tamper_exact_objective),
    ("receipt_signature", _tamper_receipt_signature),
    ("receipt_payload", _tamper_receipt_payload),
    ("comparison_conclusion", _tamper_comparison_conclusion),
    ("policy_snapshot", _tamper_policy_snapshot),
]


def _integrity_audits(container: AppContainer) -> int:
    with container.database.engine.connect() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action='optimization.benchmark_integrity_failed'"
                )
            ).scalar_one()
        )


@pytest.mark.parametrize("name,tamper", _TAMPERS, ids=[n for n, _ in _TAMPERS])
def test_tampered_persisted_evidence_fails_reauth(
    container: AppContainer, name: str, tamper: Callable[[AppContainer, str], None]
) -> None:
    bid = _accepted_benchmark(container)
    tamper(container, bid)
    auth = container.optimization_service.read_benchmark_evidence(bid)
    assert auth.found and not auth.authenticated and auth.integrity_failed
    assert auth.safe_conclusion() == "insufficient-evidence"  # no positive conclusion served
    assert _integrity_audits(container) >= 1  # a tamper/integrity audit was written


def test_run_list_does_not_label_tampered_run_verified(container: AppContainer) -> None:
    bid = _accepted_benchmark(container)
    _tamper_exact_objective(container, bid)
    summaries = container.optimization_service.list_run_summaries(50, 0)
    row = next(a for a in summaries if a.run is not None and a.run.id == bid)
    assert not row.authenticated and row.integrity_failed


def test_artifacts_endpoint_withholds_tampered_evidence(client_container) -> None:
    client, container = client_container
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    _tamper_exact_objective(container, run.id)
    resp = client.get(f"/api/v1/optimization/runs/{run.id}/artifacts")
    assert resp.status_code == 422  # bounded integrity error, not a positive serve


@pytest.fixture
def client_container(container: AppContainer):
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    with TestClient(create_app(container)) as client:
        yield client, container
