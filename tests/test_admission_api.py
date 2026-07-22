"""Focused trusted-transport tests for the U7.5A Admission JSON API."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.routers.admission import get_trusted_clock
from orbitmind.core.config import Settings

_BASE_URL = "http://127.0.0.1:8000"
_T0 = datetime(2026, 7, 22, 12, tzinfo=UTC)


@pytest.fixture
def admission_api(tmp_path: Path) -> Iterator[tuple[TestClient, FastAPI, AppContainer]]:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'admission-api.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
    )
    container = AppContainer(settings=settings, caller_owns_lifecycle=True)
    app = create_app(container)
    app.dependency_overrides[get_trusted_clock] = lambda: _T0
    try:
        with TestClient(app, base_url=_BASE_URL, client=("127.0.0.1", 50_000)) as client:
            yield client, app, container
    finally:
        container.shutdown()


def _payload(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "proposal_id": "prop-00000001",
        "operation_kind": "read_repository",
        "requested_capability": "repository_read",
        "requested_scope": {
            "resource_type": "repository",
            "resource_id": "orbitmind-main",
            "constraints": [],
        },
        "side_effect_class": "local_read",
        "risk_class": "low",
        "purpose": "Read bounded repository evidence.",
        "requested_at": "2026-07-01T00:00:00Z",
        "idempotency_key": "admission-key-001",
        "provenance_refs": ["review:u7.5a"],
    }
    values.update(overrides)
    return values


def _post(client: TestClient, payload: dict[str, object], **headers: str) -> object:
    return client.post(
        "/api/admission/proposals",
        json=payload,
        headers={"Content-Type": "application/json", **headers},
    )


def test_create_replay_conflict_and_trusted_fields(
    admission_api: tuple[TestClient, FastAPI, AppContainer],
) -> None:
    client, _app, _container = admission_api
    created = _post(client, _payload())
    assert created.status_code == 201
    record = created.json()["record"]
    assert record["owner_id"] == "local-owner"
    assert record["actor_id"] == "local-operator"
    assert record["evaluated_at"] == _T0.isoformat().replace("+00:00", "Z")
    assert record["policy_version"] == "operation-admission-v0"
    assert created.json()["execution_authority"] is False
    assert "access-control-allow-origin" not in created.headers

    replay = _post(client, _payload())
    assert replay.status_code == 200
    assert replay.json()["record"] == record

    conflict = _post(client, _payload(proposal_id="prop-00000002"))
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "idempotency_conflict",
        "message": "admission idempotency key was reused for a different proposal",
    }


@pytest.mark.parametrize(
    "server_field",
    [
        "owner_id",
        "actor_id",
        "evaluated_at",
        "policy_version",
        "resolved_authority_grant_id",
        "admission_id",
        "created_at",
        "proposal_fingerprint",
        "decision_checksum",
        "record_identity",
        "disposition",
    ],
)
def test_body_cannot_set_server_owned_fields(
    admission_api: tuple[TestClient, FastAPI, AppContainer], server_field: str
) -> None:
    client, _app, _container = admission_api
    response = _post(client, _payload(**{server_field: "attacker-value"}))
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_transport_origin_body_bounds_and_loopback(
    admission_api: tuple[TestClient, FastAPI, AppContainer],
) -> None:
    client, app, _container = admission_api
    wrong_type = client.post(
        "/api/admission/proposals", content="{}", headers={"Content-Type": "text/plain"}
    )
    assert wrong_type.status_code == 422
    assert _post(client, _payload(), **{"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert _post(client, _payload(), Origin="https://hostile.invalid").status_code == 403
    same_origin = _post(
        client,
        _payload(),
        **{"Sec-Fetch-Site": "same-origin", "Origin": _BASE_URL},
    )
    assert same_origin.status_code == 201

    oversized = client.post(
        "/api/admission/proposals",
        content=b'"' + (b"x" * 17_000) + b'"',
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 422

    with TestClient(app, base_url=_BASE_URL, client=("192.0.2.10", 50_001)) as remote_client:
        assert _post(remote_client, _payload()).status_code == 403


def test_owner_scoped_reads_lists_and_null_authority_projection(
    admission_api: tuple[TestClient, FastAPI, AppContainer],
) -> None:
    client, app, _container = admission_api
    created = _post(client, _payload())
    admission_id = created.json()["record"]["admission_id"]

    assert client.get(f"/api/admission/records/{admission_id}").status_code == 200
    listing = client.get("/api/admission/records", params={"limit": 1})
    assert listing.status_code == 200
    assert listing.json()["page_size"] == 1
    chain = client.get(f"/api/admission/records/{admission_id}/evidence-chain")
    assert chain.status_code == 200
    assert chain.json()["authority"] is None
    assert chain.json()["execution_authority"] is False

    app.dependency_overrides[get_current_owner_id] = lambda: "owner-other-01"
    foreign = client.get(f"/api/admission/records/{admission_id}")
    assert foreign.status_code == 404
    assert foreign.json()["code"] == "admission_record_not_found"
