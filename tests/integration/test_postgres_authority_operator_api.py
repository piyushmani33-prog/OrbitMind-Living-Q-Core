"""Live PostgreSQL coverage for the U7.3 Authority Operator API.

The inherited U7.1 persistence suite covers owner-scoped concurrency; the U7.2
lifecycle suite covers transaction and causality behavior. This slice exercises
the reviewed API transport over that migrated schema without calling create_all.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.core.config import Settings

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")
_TABLES = (
    "authority_evaluations",
    "authority_revocations",
    "authority_capability_grants",
    "authority_approval_decisions",
    "authority_approval_requests",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]


@pytest.fixture
def pg_container(tmp_path: Path) -> Iterator[AppContainer]:
    """Use an Alembic-migrated disposable PostgreSQL database unchanged by ORM DDL."""

    assert _PG_URL is not None
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
    )
    container = AppContainer(settings=settings)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    inspector = inspect(container.database.engine)
    missing = [table for table in _TABLES if not inspector.has_table(table)]
    if missing:
        pytest.skip(f"authority tables absent (run alembic upgrade head): {missing}")
    with container.database.engine.begin() as connection:
        connection.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    try:
        yield container
    finally:
        container.database.dispose()


@pytest.fixture
def pg_client(pg_container: AppContainer) -> Iterator[TestClient]:
    app = create_app(pg_container)
    app.dependency_overrides[get_current_owner_id] = lambda: "owner-postgres-a"
    with TestClient(
        app,
        base_url="http://127.0.0.1:8000",
        raise_server_exceptions=False,
        client=("127.0.0.1", 50_000),
    ) as client:
        yield client


def _request_payload(
    *, request_id: str = "req-00000001", key: str = "request-key-001"
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "subject": {"subject_type": "agent", "subject_id": "agent-dev-0001"},
        "capability": "repository_read",
        "scope": {"resource_type": "repository", "resource_id": "orbitmind-main"},
        "purpose": "Read one bounded PostgreSQL authority record.",
        "policy_version": "authority-policy-v1",
        "requested_at": "2026-07-19T00:00:00Z",
        "valid_from": "2026-07-19T00:00:00Z",
        "expires_at": "2026-08-19T00:00:00Z",
        "idempotency_key": key,
    }


def _decision_payload(
    *, decision_id: str = "dec-00000001", outcome: str = "approved"
) -> dict[str, object]:
    return {
        "decision_id": decision_id,
        "outcome": outcome,
        "decided_at": "2026-07-19T01:00:00Z",
        "reason": "Recorded for PostgreSQL API coverage.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"{decision_id}-key",
    }


def _grant_payload(*, decision_id: str = "dec-00000001") -> dict[str, object]:
    return {
        "grant_id": "grant-00000001",
        "decision_id": decision_id,
        "issued_at": "2026-07-19T02:00:00Z",
        "policy_version": "authority-policy-v1",
        "idempotency_key": "grant-key-001",
    }


def _post(client: TestClient, path: str, payload: dict[str, object]) -> object:
    return client.post(path, json=payload, headers={"Content-Type": "application/json"})


def _create_approved_grant(client: TestClient) -> None:
    assert _post(client, "/api/authority/approval-requests", _request_payload()).status_code == 201
    assert (
        _post(
            client,
            "/api/authority/approval-requests/req-00000001/decisions",
            _decision_payload(),
        ).status_code
        == 201
    )
    assert _post(client, "/api/authority/grants", _grant_payload()).status_code == 201


def test_postgres_api_records_full_chain_with_exact_grant_reads(pg_client: TestClient) -> None:
    _create_approved_grant(pg_client)
    authorized = _post(
        pg_client,
        "/api/authority/evaluations",
        {
            "evaluation_id": "eval-00000001",
            "grant_id": "grant-00000001",
            "evaluation_time": "2026-07-19T03:00:00Z",
            "delegation_requested": False,
            "policy_version": "authority-policy-v1",
            "idempotency_key": "evaluation-key-001",
        },
    )
    revocation = _post(
        pg_client,
        "/api/authority/grants/grant-00000001/revocations",
        {
            "revocation_id": "rvk-00000001",
            "effective_at": "2026-07-20T00:00:00Z",
            "recorded_at": "2026-07-19T03:30:00Z",
            "reason": "Revoked after PostgreSQL API review.",
            "policy_version": "authority-policy-v1",
            "idempotency_key": "revocation-key-001",
        },
    )
    revoked = _post(
        pg_client,
        "/api/authority/evaluations",
        {
            "evaluation_id": "eval-00000002",
            "grant_id": "grant-00000001",
            "evaluation_time": "2026-07-21T00:00:00Z",
            "delegation_requested": False,
            "policy_version": "authority-policy-v1",
            "idempotency_key": "evaluation-key-002",
        },
    )

    assert authorized.status_code == 201
    assert authorized.json()["evaluation"]["authorized"] is True
    assert revocation.status_code == 201
    assert revoked.status_code == 201
    assert revoked.json()["evaluation"]["reason_code"] == "revoked"
    assert (
        len(pg_client.get("/api/authority/grants/grant-00000001/revocations").json()["items"]) == 1
    )
    assert (
        len(
            pg_client.get("/api/authority/grants/grant-00000001/evaluations?limit=1").json()[
                "items"
            ]
        )
        == 1
    )
    chain = pg_client.get("/api/authority/approval-requests/req-00000001/chain")
    assert chain.status_code == 200
    assert len(chain.json()["approval_decisions"]) == 1
    assert len(chain.json()["capability_grants"]) == 1


def test_postgres_api_replay_conflict_rejected_grant_and_owner_isolation(
    pg_client: TestClient,
) -> None:
    first = _post(pg_client, "/api/authority/approval-requests", _request_payload())
    replay = _post(pg_client, "/api/authority/approval-requests", _request_payload())
    terminal = _post(
        pg_client,
        "/api/authority/approval-requests/req-00000001/decisions",
        _decision_payload(outcome="rejected"),
    )
    refusal = _post(pg_client, "/api/authority/grants", _grant_payload())
    conflicting_terminal = _post(
        pg_client,
        "/api/authority/approval-requests/req-00000001/decisions",
        _decision_payload(decision_id="dec-00000002"),
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert terminal.status_code == 201
    assert refusal.status_code == 422
    assert refusal.json()["code"] == "authority_decision_rejected"
    assert conflicting_terminal.status_code == 409

    pg_client.app.dependency_overrides[get_current_owner_id] = lambda: "owner-postgres-b"
    try:
        assert pg_client.get("/api/authority/approval-requests/req-00000001").status_code == 404
        assert pg_client.get("/api/authority/grants").json()["items"] == []
    finally:
        pg_client.app.dependency_overrides[get_current_owner_id] = lambda: "owner-postgres-a"


def test_postgres_api_rejected_mutation_rolls_back_without_partial_grant(
    pg_client: TestClient,
) -> None:
    _create_approved_grant(pg_client)
    conflicting = _grant_payload()
    conflicting["grant_id"] = "grant-00000002"
    conflicting["policy_version"] = "authority-policy-v2"
    conflicting["idempotency_key"] = "grant-key-conflict"

    response = _post(pg_client, "/api/authority/grants", conflicting)
    grants = pg_client.get("/api/authority/grants")
    assert response.status_code == 422
    assert response.json()["code"] == "authority_policy_mismatch"
    assert [item["grant_id"] for item in grants.json()["items"]] == ["grant-00000001"]
