"""Focused U7.3 Authority Operator JSON API and shared page-CSRF coverage."""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.camera.csrf import CAMERA_CSRF_POLICY, CameraCsrfRoute
from orbitmind.core.config import Settings
from orbitmind.core.page_csrf import (
    AUTHORITY_WORKBENCH_CSRF_POLICY,
    AuthorityWorkbenchCsrfRoute,
    PageCsrfRegistry,
    PageCsrfRejectedError,
    PageCsrfRequestAuthority,
    PageCsrfScope,
)
from orbitmind.orchestration.authority_lifecycle import MAX_OPERATOR_PAGE_SIZE

_BASE_URL = "http://127.0.0.1:8000"
_T0 = datetime(2026, 7, 19, tzinfo=UTC)


class _Secrets:
    def __init__(self, domain: bytes) -> None:
        self._domain = domain
        self._counter = 0

    def __call__(self) -> bytes:
        self._counter += 1
        return hashlib.sha256(self._domain + self._counter.to_bytes(8, "big")).digest()


@pytest.fixture
def authority_client(tmp_path: Path) -> Iterator[tuple[TestClient, AppContainer]]:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'authority-api.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
    )
    container = AppContainer(settings=settings, caller_owns_lifecycle=True)
    try:
        with TestClient(
            create_app(container), base_url=_BASE_URL, client=("127.0.0.1", 50_000)
        ) as client:
            yield client, container
    finally:
        container.shutdown()


def _request_payload(
    *, request_id: str = "req-00000001", key: str = "request-key-001"
) -> dict[str, object]:
    return {
        "request_id": request_id,
        "subject": {"subject_type": "agent", "subject_id": "agent-dev-0001"},
        "capability": "repository_read",
        "scope": {
            "resource_type": "repository",
            "resource_id": "orbitmind-main",
            "constraints": [{"name": "ref", "value": "rev-abc123"}],
        },
        "purpose": "Read one pinned revision for review evidence.",
        "policy_version": "authority-policy-v1",
        "requested_at": "2026-07-19T00:00:00Z",
        "valid_from": "2026-07-19T00:00:00Z",
        "expires_at": "2026-08-19T00:00:00Z",
        "idempotency_key": key,
    }


def _decision_payload(*, decision_id: str = "dec-00000001") -> dict[str, object]:
    return {
        "decision_id": decision_id,
        "outcome": "approved",
        "decided_at": "2026-07-19T01:00:00Z",
        "reason": "Approved for one bounded review.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"{decision_id}-key",
    }


def _grant_payload(*, grant_id: str = "grant-00000001") -> dict[str, object]:
    return {
        "grant_id": grant_id,
        "decision_id": "dec-00000001",
        "issued_at": "2026-07-19T02:00:00Z",
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"{grant_id}-key",
    }


def _revocation_payload(
    *,
    revocation_id: str = "rvk-00000001",
    effective_at: str = "2026-07-20T00:00:00Z",
    recorded_at: str = "2026-07-19T03:00:00Z",
) -> dict[str, object]:
    return {
        "revocation_id": revocation_id,
        "effective_at": effective_at,
        "recorded_at": recorded_at,
        "reason": "Revoked after the bounded review completed.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"{revocation_id}-key",
    }


def _evaluation_payload(
    *,
    evaluation_id: str = "eval-00000001",
    evaluation_time: str = "2026-07-19T04:00:00Z",
) -> dict[str, object]:
    return {
        "evaluation_id": evaluation_id,
        "grant_id": "grant-00000001",
        "evaluation_time": evaluation_time,
        "delegation_requested": False,
        "policy_version": "authority-policy-v1",
        "idempotency_key": f"{evaluation_id}-key",
    }


def _json_post(client: TestClient, path: str, payload: dict[str, object]) -> object:
    return client.post(path, json=payload, headers={"Content-Type": "application/json"})


def _create_approved_grant(client: TestClient) -> None:
    assert (
        _json_post(client, "/api/authority/approval-requests", _request_payload()).status_code
        == 201
    )
    assert (
        _json_post(
            client,
            "/api/authority/approval-requests/req-00000001/decisions",
            _decision_payload(),
        ).status_code
        == 201
    )
    assert _json_post(client, "/api/authority/grants", _grant_payload()).status_code == 201


def test_json_api_persists_the_explicit_authority_lifecycle(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    _create_approved_grant(client)

    evaluation = _json_post(client, "/api/authority/evaluations", _evaluation_payload())
    assert evaluation.status_code == 201
    assert evaluation.json()["evaluation"]["authorized"] is True
    assert evaluation.json()["enforced"] is False
    newer_evaluation = _json_post(
        client,
        "/api/authority/evaluations",
        _evaluation_payload(evaluation_id="eval-00000002", evaluation_time="2026-07-19T05:00:00Z"),
    )
    assert newer_evaluation.status_code == 201

    revocation = _json_post(
        client,
        "/api/authority/grants/grant-00000001/revocations",
        _revocation_payload(),
    )
    assert revocation.status_code == 201

    chain = client.get("/api/authority/approval-requests/req-00000001/chain")
    assert chain.status_code == 200
    body = chain.json()
    assert body["owner_id"] == "local-owner"
    assert body["approval_request"]["requested_by"] == "local-operator"
    assert body["approval_decisions"][0]["decided_by"]["subject_id"] == "local-operator"
    assert body["capability_grants"][0]["issued_by"]["subject_id"] == "local-operator"
    assert len(body["revocations"]) == 1
    assert len(body["evaluations"]) == 2
    assert client.get("/api/authority/grants/grant-00000001/revocations").status_code == 200
    assert client.get("/api/authority/grants/grant-00000001/evaluations").status_code == 200

    grant = client.get("/api/authority/grants/grant-00000001")
    assert grant.status_code == 200
    assert grant.json()["revocation_count"] == 1
    assert grant.json()["latest_evaluation"]["evaluation_id"] == "eval-00000002"


def test_json_api_grant_projection_and_exact_grant_lists_use_truthful_bounds(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    _create_approved_grant(client)

    for index in range(1, MAX_OPERATOR_PAGE_SIZE + 2):
        evaluation_id = f"eval-{index:08d}"
        evaluation_time = (
            (_T0 + timedelta(hours=3, minutes=index)).isoformat().replace("+00:00", "Z")
        )
        evaluation = _json_post(
            client,
            "/api/authority/evaluations",
            _evaluation_payload(evaluation_id=evaluation_id, evaluation_time=evaluation_time),
        )
        assert evaluation.status_code == 201

    replayed_evaluation = _json_post(
        client,
        "/api/authority/evaluations",
        _evaluation_payload(
            evaluation_id="eval-00000051",
            evaluation_time=(_T0 + timedelta(hours=3, minutes=51))
            .isoformat()
            .replace("+00:00", "Z"),
        ),
    )
    assert replayed_evaluation.status_code == 200

    for index in range(1, MAX_OPERATOR_PAGE_SIZE + 2):
        revocation_id = f"rvk-{index:08d}"
        revocation = _json_post(
            client,
            "/api/authority/grants/grant-00000001/revocations",
            _revocation_payload(
                revocation_id=revocation_id,
                effective_at=f"2026-08-{(index % 28) + 1:02d}T00:00:00Z",
                recorded_at=f"2026-07-19T03:{index:02d}:00Z",
            ),
        )
        assert revocation.status_code == 201

    replay = _json_post(client, "/api/authority/grants", _grant_payload())
    assert replay.status_code == 200
    assert replay.json()["revocation_count"] == MAX_OPERATOR_PAGE_SIZE + 1
    assert replay.json()["latest_evaluation"]["evaluation_id"] == "eval-00000051"

    replayed_revocation = _json_post(
        client,
        "/api/authority/grants/grant-00000001/revocations",
        _revocation_payload(
            revocation_id="rvk-00000051",
            effective_at="2026-08-24T00:00:00Z",
            recorded_at="2026-07-19T03:51:00Z",
        ),
    )
    assert replayed_revocation.status_code == 200

    revocations = client.get("/api/authority/grants/grant-00000001/revocations?limit=1").json()
    evaluations = client.get("/api/authority/grants/grant-00000001/evaluations?limit=1").json()
    assert revocations["page_size"] == 1
    assert revocations["truncated"] is True
    assert evaluations["page_size"] == 1
    assert evaluations["truncated"] is True


def test_json_api_replays_identical_input_and_rejects_conflicting_terminal_decision(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    first = _json_post(client, "/api/authority/approval-requests", _request_payload())
    replay = _json_post(client, "/api/authority/approval-requests", _request_payload())
    assert first.status_code == 201
    assert replay.status_code == 200

    first_decision = _json_post(
        client,
        "/api/authority/approval-requests/req-00000001/decisions",
        _decision_payload(),
    )
    conflict = _json_post(
        client,
        "/api/authority/approval-requests/req-00000001/decisions",
        _decision_payload(decision_id="dec-00000002"),
    )
    assert first_decision.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "authority_request_already_decided",
        "message": "approval request already has a terminal decision",
    }


def test_json_api_refuses_grant_issuance_from_a_rejected_decision(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    assert (
        _json_post(client, "/api/authority/approval-requests", _request_payload()).status_code
        == 201
    )
    assert (
        _json_post(
            client,
            "/api/authority/approval-requests/req-00000001/decisions",
            _decision_payload(),
        ).status_code
        == 201
    )
    rejected = _decision_payload()
    rejected["outcome"] = "rejected"
    rejected["decision_id"] = "dec-00000002"
    rejected["idempotency_key"] = "rejected-decision-key"

    second_client = client.app
    second_client.dependency_overrides[get_current_owner_id] = lambda: "second-owner"
    try:
        assert (
            _json_post(client, "/api/authority/approval-requests", _request_payload()).status_code
            == 201
        )
        assert (
            _json_post(
                client,
                "/api/authority/approval-requests/req-00000001/decisions",
                rejected,
            ).status_code
            == 201
        )
        grant_from_rejection = _grant_payload()
        grant_from_rejection["decision_id"] = "dec-00000002"
        refusal = _json_post(client, "/api/authority/grants", grant_from_rejection)
    finally:
        second_client.dependency_overrides.clear()
    assert refusal.status_code == 422
    assert refusal.json()["code"] == "authority_decision_rejected"


def test_json_api_rejects_owner_and_actor_injection_before_persistence(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    forged_owner = _request_payload()
    forged_owner["owner_id"] = "another-owner"
    forged_actor = _request_payload()
    forged_actor["requested_by"] = "another-operator"

    assert _json_post(client, "/api/authority/approval-requests", forged_owner).status_code == 422
    assert _json_post(client, "/api/authority/approval-requests", forged_actor).status_code == 422
    assert client.get("/api/authority/approval-requests").json()["items"] == []


def test_json_api_owner_scope_is_enforced_by_the_trusted_local_context(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    assert (
        _json_post(client, "/api/authority/approval-requests", _request_payload()).status_code
        == 201
    )
    app = client.app
    app.dependency_overrides[get_current_owner_id] = lambda: "other-owner"
    try:
        assert client.get("/api/authority/approval-requests/req-00000001").status_code == 404
        assert client.get("/api/authority/approval-requests").json()["items"] == []
    finally:
        app.dependency_overrides.clear()


def test_json_api_rejects_non_loopback_transport_before_read_or_mutation(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    _client, container = authority_client
    with TestClient(
        create_app(container), base_url=_BASE_URL, client=("203.0.113.10", 50_001)
    ) as remote_client:
        assert remote_client.get("/api/authority/approval-requests").status_code == 403
        assert (
            _json_post(
                remote_client, "/api/authority/approval-requests", _request_payload()
            ).status_code
            == 403
        )


def test_json_api_list_truncation_uses_a_single_bounded_probe_row(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    assert (
        _json_post(client, "/api/authority/approval-requests", _request_payload()).status_code
        == 201
    )
    complete = client.get("/api/authority/approval-requests?limit=1").json()
    assert complete["page_size"] == 1
    assert complete["truncated"] is False

    assert (
        _json_post(
            client,
            "/api/authority/approval-requests",
            _request_payload(request_id="req-00000002", key="request-key-002"),
        ).status_code
        == 201
    )
    truncated = client.get("/api/authority/approval-requests?limit=1").json()
    assert truncated["page_size"] == 1
    assert truncated["truncated"] is True


def test_json_api_requires_canonical_json_content_type_and_bounded_query_limits(
    authority_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = authority_client
    response = client.post(
        "/api/authority/approval-requests",
        content=b"{}",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 422
    assert client.get("/api/authority/approval-requests?limit=0").status_code == 422
    assert client.get("/api/authority/approval-requests?limit=201").status_code == 422


def test_shared_registry_is_scope_and_route_isolated() -> None:
    registry = PageCsrfRegistry(
        clock=lambda: _T0,
        page_session_id_generator=_Secrets(b"page"),
        csrf_token_generator=_Secrets(b"token"),
        process_binding_key=hashlib.sha256(b"binding").digest(),
        policies=(CAMERA_CSRF_POLICY, AUTHORITY_WORKBENCH_CSRF_POLICY),
    )
    authority = registry.issue(PageCsrfScope.AUTHORITY_WORKBENCH)
    camera = registry.issue(PageCsrfScope.CAMERA)
    assert registry.active_session_count(PageCsrfScope.AUTHORITY_WORKBENCH) == 1
    assert registry.active_session_count(PageCsrfScope.CAMERA) == 1

    request = PageCsrfRequestAuthority(
        scope=PageCsrfScope.AUTHORITY_WORKBENCH,
        method="POST",
        route=AuthorityWorkbenchCsrfRoute.CREATE_REQUEST,
        scheme="http",
        host_values=("127.0.0.1:8000",),
        origin_values=(_BASE_URL,),
        sec_fetch_site_values=("same-origin",),
        forwarded_header_names=(),
        page_session_cookie=authority.page_session_id,
        csrf_token_values=(authority.csrf_token,),
        selected_port=8000,
    )
    rotated = registry.validate_and_rotate(request)
    assert rotated.generation == 2

    with pytest.raises(PageCsrfRejectedError):
        registry.validate_and_rotate(request)
    with pytest.raises(PageCsrfRejectedError):
        registry.validate_and_rotate(
            PageCsrfRequestAuthority(
                scope=PageCsrfScope.CAMERA,
                method="POST",
                route=CameraCsrfRoute.CREATE_SESSION,
                scheme="http",
                host_values=("127.0.0.1:8000",),
                origin_values=(_BASE_URL,),
                sec_fetch_site_values=("same-origin",),
                forwarded_header_names=(),
                page_session_cookie=authority.page_session_id,
                csrf_token_values=(camera.csrf_token,),
                selected_port=8000,
            )
        )


def test_shared_registry_fails_closed_for_protocol_mismatch() -> None:
    registry = PageCsrfRegistry(
        clock=lambda: _T0 + timedelta(seconds=1),
        page_session_id_generator=_Secrets(b"page"),
        csrf_token_generator=_Secrets(b"token"),
        process_binding_key=hashlib.sha256(b"binding").digest(),
        policies=(AUTHORITY_WORKBENCH_CSRF_POLICY,),
    )
    issued = registry.issue(PageCsrfScope.AUTHORITY_WORKBENCH)
    with pytest.raises(PageCsrfRejectedError):
        registry.validate_and_rotate(
            PageCsrfRequestAuthority(
                scope=PageCsrfScope.AUTHORITY_WORKBENCH,
                method="POST",
                route=AuthorityWorkbenchCsrfRoute.CREATE_REQUEST,
                scheme="http",
                host_values=("127.0.0.1:8000",),
                origin_values=("http://attacker.invalid",),
                sec_fetch_site_values=("same-origin",),
                forwarded_header_names=(),
                page_session_cookie=issued.page_session_id,
                csrf_token_values=(issued.csrf_token,),
                selected_port=8000,
            )
        )


def test_authority_router_uses_lifecycle_services_and_no_legacy_csrf_module() -> None:
    root = Path(__file__).resolve().parents[1]
    router_source = (root / "src/orbitmind/api/routers/authority.py").read_text(encoding="utf-8")
    tree = ast.parse(router_source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
        for alias in node.names
    }
    assert "SqlAlchemyAuthorityRepository" not in imports
    assert "authority_csrf" not in router_source
    assert "authority_workbench_port" not in router_source
    assert "custom_tle_handoff_port" in router_source
    assert "read_approval_request_for_decision" in router_source
    assert "read_authority_chain_for_decision" not in router_source
