"""Classified U7.5A acceptance harness (A/B/C; execution remains D-deferred)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from orbitmind.admission.contracts import (
    OPERATION_PROFILES,
    AdmissionOperationKind,
    AdmissionOutcome,
    AdmissionReasonCode,
    OperationProposal,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.routers.admission import get_trusted_clock
from orbitmind.core.config import Settings
from orbitmind.orchestration.admission_lifecycle import admit_operation
from orbitmind.persistence.admission_models import OperationAdmissionRecordRow
from orbitmind.persistence.admission_repository import (
    AdmissionRecordCorruptError,
    SqlAlchemyAdmissionRepository,
)

_BASE_URL = "http://127.0.0.1:8000"
_T0 = datetime(2026, 7, 22, 12, tzinfo=UTC)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'acceptance.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
    )


@pytest.fixture
def acceptance_api(tmp_path: Path) -> Iterator[tuple[TestClient, FastAPI, AppContainer]]:
    container = AppContainer(settings=_settings(tmp_path), caller_owns_lifecycle=True)
    app = create_app(container)
    app.dependency_overrides[get_trusted_clock] = lambda: _T0
    try:
        with TestClient(app, base_url=_BASE_URL, client=("127.0.0.1", 50_000)) as client:
            yield client, app, container
    finally:
        container.shutdown()


def _json_post(client: TestClient, path: str, payload: dict[str, object]) -> object:
    return client.post(path, json=payload, headers={"Content-Type": "application/json"})


def _authority_grant(
    client: TestClient,
    *,
    suffix: str,
    capability: str,
    expires_at: datetime = _T0 + timedelta(days=1),
) -> tuple[str, str]:
    request_id = f"req-{suffix}-00001"
    decision_id = f"dec-{suffix}-00001"
    grant_id = f"grant-{suffix}-00001"
    request = {
        "request_id": request_id,
        "subject": {"subject_type": "operator", "subject_id": "local-operator"},
        "capability": capability,
        "scope": {
            "resource_type": "repository",
            "resource_id": "orbitmind-main",
            "constraints": [],
        },
        "purpose": "Bounded U7.5A acceptance evidence.",
        "policy_version": "authority-policy-v1",
        "requested_at": (_T0 - timedelta(days=2)).isoformat(),
        "valid_from": (_T0 - timedelta(days=1)).isoformat(),
        "expires_at": expires_at.isoformat(),
        "idempotency_key": f"request-{suffix}-key",
    }
    assert _json_post(client, "/api/authority/approval-requests", request).status_code == 201
    decision = {
        "decision_id": decision_id,
        "outcome": "approved",
        "decided_at": (_T0 - timedelta(hours=12)).isoformat(),
        "reason": "Approved for bounded acceptance.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"decision-{suffix}-key",
    }
    assert (
        _json_post(
            client, f"/api/authority/approval-requests/{request_id}/decisions", decision
        ).status_code
        == 201
    )
    grant = {
        "grant_id": grant_id,
        "decision_id": decision_id,
        "issued_at": (_T0 - timedelta(hours=6)).isoformat(),
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"grant-{suffix}-key",
    }
    assert _json_post(client, "/api/authority/grants", grant).status_code == 201
    return request_id, grant_id


def _proposal(
    *,
    kind: AdmissionOperationKind,
    suffix: str,
    grant_id: str | None = None,
) -> dict[str, object]:
    profile = OPERATION_PROFILES[kind]
    return {
        "proposal_id": f"prop-{suffix}-00001",
        "operation_kind": kind.value,
        "requested_capability": profile.required_capability,
        "requested_scope": {
            "resource_type": "repository",
            "resource_id": "orbitmind-main",
            "constraints": [],
        },
        "side_effect_class": profile.side_effect_class.value,
        "risk_class": profile.risk_class.value,
        "purpose": "Bounded U7.5A acceptance evidence.",
        "requested_authority_grant_id": grant_id,
        "requested_at": _T0.isoformat(),
        "idempotency_key": f"admission-{suffix}-key",
    }


def test_class_a_operator_visible_admission_journey(
    acceptance_api: tuple[TestClient, FastAPI, AppContainer],
) -> None:
    client, _app, _container = acceptance_api
    auto = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(kind=AdmissionOperationKind.READ_REPOSITORY, suffix="auto"),
    )
    assert auto.status_code == 201
    assert auto.json()["record"]["outcome"] == "admitted"

    no_grant = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(kind=AdmissionOperationKind.PROPOSE_FILE_CHANGE, suffix="missing"),
    )
    assert no_grant.json()["record"]["outcome"] == "denied"

    request_id, grant_id = _authority_grant(
        client, suffix="write", capability="repository_write_proposal"
    )
    admitted = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(
            kind=AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            suffix="valid",
            grant_id=grant_id,
        ),
    )
    assert admitted.json()["record"]["outcome"] == "admitted"
    admission_id = admitted.json()["record"]["admission_id"]
    assert client.get(f"/api/admission/records/{admission_id}").status_code == 200
    assert client.get("/api/admission/records").status_code == 200
    assert client.get(f"/api/admission/records/{admission_id}/evidence-chain").status_code == 200
    request_chain = client.get(f"/api/admission/authority-chains/{request_id}")
    assert [item["admission_id"] for item in request_chain.json()["admissions"]] == [admission_id]

    _request_id, approval_grant = _authority_grant(
        client, suffix="install", capability="dependency_install"
    )
    withheld = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(
            kind=AdmissionOperationKind.INSTALL_DEPENDENCY,
            suffix="withhold",
            grant_id=approval_grant,
        ),
    )
    assert withheld.json()["record"]["outcome"] == "approval_required"
    forbidden = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(kind=AdmissionOperationKind.DEPLOY, suffix="forbid"),
    )
    assert forbidden.json()["record"]["outcome"] == "denied"


def test_class_b_controlled_clock_expiry_revocation_and_actor_mismatch(
    acceptance_api: tuple[TestClient, FastAPI, AppContainer],
) -> None:
    client, app, container = acceptance_api
    _request_id, expiring_grant = _authority_grant(
        client,
        suffix="expiry",
        capability="repository_write_proposal",
        expires_at=_T0 + timedelta(minutes=1),
    )
    app.dependency_overrides[get_trusted_clock] = lambda: _T0 + timedelta(minutes=2)
    expired = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(
            kind=AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            suffix="expired",
            grant_id=expiring_grant,
        ),
    )
    assert expired.json()["record"]["primary_reason_code"] == "authority_expired"

    app.dependency_overrides[get_trusted_clock] = lambda: _T0
    _request_id, revoked_grant = _authority_grant(
        client, suffix="revoke", capability="repository_write_proposal"
    )
    revocation = {
        "revocation_id": "rvk-revoke-00001",
        "effective_at": (_T0 - timedelta(seconds=1)).isoformat(),
        "recorded_at": (_T0 - timedelta(seconds=1)).isoformat(),
        "reason": "Revoked by controlled acceptance harness.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": "revocation-acceptance-key",
    }
    assert (
        _json_post(
            client, f"/api/authority/grants/{revoked_grant}/revocations", revocation
        ).status_code
        == 201
    )
    revoked = _json_post(
        client,
        "/api/admission/proposals",
        _proposal(
            kind=AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            suffix="revoked",
            grant_id=revoked_grant,
        ),
    )
    assert revoked.json()["record"]["primary_reason_code"] == "authority_revoked"

    profile = OPERATION_PROFILES[AdmissionOperationKind.READ_REPOSITORY]
    mismatch = OperationProposal(
        proposal_id="prop-actor-00001",
        owner_id="local-owner",
        actor_id="agent-dev-0001",
        actor_type=ProposalActorType.AGENT,
        operation_kind=AdmissionOperationKind.READ_REPOSITORY.value,
        requested_capability=profile.required_capability,
        requested_scope=ProposalScope(resource_type="repository", resource_id="orbitmind-main"),
        side_effect_class=profile.side_effect_class,
        risk_class=profile.risk_class,
        purpose="Controlled actor mismatch probe.",
        requested_at=_T0,
        idempotency_key="actor-mismatch-key",
    )
    with container.database.session() as session:
        result = admit_operation(
            session=session,
            proposal=mismatch,
            authoritative_owner_id="local-owner",
            authoritative_actor_id="local-operator",
            evaluated_at=_T0,
        )
    assert result.record.outcome is AdmissionOutcome.DENIED
    assert result.record.primary_reason_code is AdmissionReasonCode.ACTOR_MISMATCH


def test_class_b_real_sqlite_restart_and_tamper_fail_closed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    first = AppContainer(settings=settings, caller_owns_lifecycle=True)
    first_app = create_app(first)
    first_app.dependency_overrides[get_trusted_clock] = lambda: _T0
    with TestClient(first_app, base_url=_BASE_URL, client=("127.0.0.1", 50_000)) as client:
        created = _json_post(
            client,
            "/api/admission/proposals",
            _proposal(kind=AdmissionOperationKind.READ_REPOSITORY, suffix="restart"),
        )
        admission_id = created.json()["record"]["admission_id"]
    first.shutdown()

    second = AppContainer(settings=settings, caller_owns_lifecycle=True)
    try:
        with TestClient(
            create_app(second), base_url=_BASE_URL, client=("127.0.0.1", 50_001)
        ) as client:
            assert client.get(f"/api/admission/records/{admission_id}").status_code == 200
        with second.database.session() as session, session.begin():
            row = session.get(OperationAdmissionRecordRow, (admission_id, "local-owner"))
            assert row is not None
            payload = dict(row.canonical_payload)
            payload["outcome"] = "denied"
            row.canonical_payload = payload
        with (
            pytest.raises(AdmissionRecordCorruptError),
            second.database.session() as session,
            session.begin(),
        ):
            SqlAlchemyAdmissionRepository(session).get_admission_record(
                owner_id="local-owner", admission_id=admission_id
            )
    finally:
        second.shutdown()
