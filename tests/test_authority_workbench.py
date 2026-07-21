"""Server-rendered U7.3 Authority Workbench boundary and CSRF coverage."""

from __future__ import annotations

import re
from collections.abc import Iterator
from http.cookies import SimpleCookie
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.responses import HTMLResponse

from orbitmind.api.app import CONTENT_SECURITY_POLICY, SECURITY_HEADERS, create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.presentation.authority import PAGE_CSS
from orbitmind.api.routers import authority as authority_router
from orbitmind.api.routers.workbench import (
    CAMERA_PREVIEW_CONTENT_SECURITY_POLICY,
    CAMERA_PREVIEW_PERMISSIONS_POLICY,
)
from orbitmind.core.config import Settings
from orbitmind.core.page_csrf import (
    AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
    AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME,
    AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_PATH,
    PageCsrfScope,
)

_BASE_URL = "http://127.0.0.1:8000"
_ORIGIN_HEADERS = {"Origin": _BASE_URL, "Sec-Fetch-Site": "same-origin"}
_TOKEN_PATTERN = re.compile(
    rf'name="{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD}"\s+value="([A-Za-z0-9_-]{{43}})"'
)


@pytest.fixture
def workbench_client(tmp_path: Path) -> Iterator[tuple[TestClient, AppContainer]]:
    settings = Settings(
        database_url=f"sqlite:///{(tmp_path / 'authority-workbench.db').as_posix()}",
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


def _form_token(client: TestClient, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    match = _TOKEN_PATTERN.search(response.text)
    assert match is not None
    return match.group(1)


def _request_form(token: str, **updates: str) -> dict[str, str]:
    fields = {
        AUTHORITY_WORKBENCH_CSRF_FORM_FIELD: token,
        "confirm": "yes",
        "request_id": "req-00000001",
        "subject_type": "agent",
        "subject_id": "agent-dev-0001",
        "capability": "repository_read",
        "scope_resource_type": "repository",
        "scope_resource_id": "orbitmind-main",
        "purpose": "Read one pinned revision for review evidence.",
        "policy_version": "authority-policy-v1",
        "requested_at": "2026-07-19T00:00:00Z",
        "valid_from": "2026-07-19T00:00:00Z",
        "expires_at": "2026-08-19T00:00:00Z",
        "idempotency_key": "request-key-001",
    }
    fields.update(updates)
    return fields


def _decision_form(token: str, **updates: str) -> dict[str, str]:
    fields = {
        AUTHORITY_WORKBENCH_CSRF_FORM_FIELD: token,
        "confirm": "yes",
        "decision_id": "dec-00000001",
        "outcome": "approved",
        "decided_at": "2026-07-19T01:00:00Z",
        "reason": "Approved for one bounded review.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": "decision-key-01",
    }
    fields.update(updates)
    return fields


def _grant_form(token: str, **updates: str) -> dict[str, str]:
    fields = {
        AUTHORITY_WORKBENCH_CSRF_FORM_FIELD: token,
        "confirm": "yes",
        "decision_id": "dec-00000001",
        "grant_id": "grant-00000001",
        "issued_at": "2026-07-19T02:00:00Z",
        "policy_version": "authority-policy-v1",
        "idempotency_key": "grant-key-001",
    }
    fields.update(updates)
    return fields


def _evaluation_form(token: str, **updates: str) -> dict[str, str]:
    fields = {
        AUTHORITY_WORKBENCH_CSRF_FORM_FIELD: token,
        "confirm": "yes",
        "evaluation_id": "eval-00000001",
        "evaluation_time": "2026-07-19T03:00:00Z",
        "policy_version": "authority-policy-v1",
        "delegation_requested": "false",
        "idempotency_key": "evaluation-key-01",
    }
    fields.update(updates)
    return fields


def _revocation_form(token: str, **updates: str) -> dict[str, str]:
    fields = {
        AUTHORITY_WORKBENCH_CSRF_FORM_FIELD: token,
        "confirm": "yes",
        "revocation_id": "rvk-00000001",
        "effective_at": "2026-07-20T00:00:00Z",
        "recorded_at": "2026-07-19T04:00:00Z",
        "reason": "Revoked after the bounded review completed.",
        "policy_version": "authority-policy-v1",
        "idempotency_key": "revocation-key-01",
    }
    fields.update(updates)
    return fields


def _post(client: TestClient, path: str, form: dict[str, str], **header_updates: str) -> object:
    headers = dict(_ORIGIN_HEADERS)
    headers.update(header_updates)
    return client.post(path, data=form, headers=headers, follow_redirects=False)


def _create_request(client: TestClient, **updates: str) -> None:
    token = _form_token(client, "/authority/workbench/requests/new")
    response = _post(client, "/authority/workbench/requests", _request_form(token, **updates))
    assert response.status_code == 303


def _record_decision(client: TestClient, **updates: str) -> None:
    token = _form_token(client, "/authority/workbench/requests/req-00000001/decide")
    response = _post(
        client,
        "/authority/workbench/requests/req-00000001/decide",
        _decision_form(token, **updates),
    )
    assert response.status_code == 303


def test_workbench_pages_are_no_store_same_origin_and_explicit_about_the_boundary(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    overview = client.get("/authority/workbench")
    form = client.get("/authority/workbench/requests/new")

    assert overview.status_code == 200
    assert overview.headers["cache-control"] == "no-store"
    assert "Authority operator overview" in overview.text
    assert "does not authorize, execute" in overview.text
    assert "or enforce" in overview.text
    assert overview.headers["referrer-policy"] == "same-origin"
    assert form.headers["cache-control"] == "no-store"
    assert form.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    for name, value in SECURITY_HEADERS.items():
        expected = "same-origin" if name == "Referrer-Policy" else value
        assert form.headers[name] == expected
    assert '<form method="post"' in form.text
    assert 'name="confirm"' in form.text
    assert "authority_csrf.py" not in form.text

    cookie = SimpleCookie()
    cookie.load(form.headers["set-cookie"])
    authority_cookie = cookie[AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME]
    assert authority_cookie["path"] == AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_PATH
    assert authority_cookie["httponly"] is True
    assert authority_cookie["samesite"].lower() == "strict"
    assert "width: min(1120px, calc(100% - 32px));" in PAGE_CSS
    assert ".grid { grid-template-columns: minmax(0, 1fr); }" in PAGE_CSS


def test_referrer_policy_override_is_bounded_to_both_workbench_path_families(
    container: AppContainer,
) -> None:
    app = create_app(container)

    def html_probe() -> HTMLResponse:
        return HTMLResponse("<p>Referrer policy probe</p>")

    for path in (
        "/authority/workbench/",
        "/workbenchish",
        "/authority/workbenchish",
        "/authority",
        "/api/authority",
    ):
        app.add_api_route(path, html_probe, methods=["GET"])

    with TestClient(app, base_url=_BASE_URL, client=("127.0.0.1", 50_002)) as client:
        camera_overview = client.get("/workbench")
        camera_nested = client.get("/workbench/camera")
        authority_overview = client.get("/authority/workbench")
        authority_trailing_slash = client.get("/authority/workbench/")
        authority_form = client.get("/authority/workbench/requests/new")
        nonmatching = {
            path: client.get(path)
            for path in (
                "/workbenchish",
                "/authority/workbenchish",
                "/authority",
                "/api/authority",
            )
        }
        authority_api = client.get("/api/authority/approval-requests")

    for response in (
        camera_overview,
        authority_overview,
        authority_trailing_slash,
        authority_form,
    ):
        assert response.status_code == 200
        assert response.headers["referrer-policy"] == "same-origin"
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert response.headers["permissions-policy"] == SECURITY_HEADERS["Permissions-Policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"

    assert camera_nested.status_code == 200
    assert camera_nested.headers["referrer-policy"] == "same-origin"
    assert (
        camera_nested.headers["content-security-policy"] == CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    )
    assert camera_nested.headers["permissions-policy"] == CAMERA_PREVIEW_PERMISSIONS_POLICY
    assert camera_nested.headers["x-content-type-options"] == "nosniff"
    assert camera_nested.headers["x-frame-options"] == "DENY"

    for response in nonmatching.values():
        assert response.status_code == 200
        assert response.headers["referrer-policy"] == "no-referrer"
        assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
        assert response.headers["permissions-policy"] == SECURITY_HEADERS["Permissions-Policy"]
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"

    assert authority_api.status_code == 200
    assert authority_api.headers["content-type"].startswith("application/json")
    assert authority_api.headers["cache-control"] == "no-store"
    assert authority_api.headers["x-content-type-options"] == "nosniff"
    assert "referrer-policy" not in authority_api.headers
    assert "content-security-policy" not in authority_api.headers
    assert "permissions-policy" not in authority_api.headers
    assert "x-frame-options" not in authority_api.headers
    assert authority_api.json() == {
        "schema_version": "authority-api-v1",
        "owner_id": "local-owner",
        "items": [],
        "page_size": 0,
        "truncated": False,
    }


def test_workbench_csrf_rejects_missing_cross_origin_cross_session_and_replayed_tokens(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    token = _form_token(client, "/authority/workbench/requests/new")
    valid = _request_form(token)

    missing = _post(
        client,
        "/authority/workbench/requests",
        _request_form(token, **{AUTHORITY_WORKBENCH_CSRF_FORM_FIELD: ""}),
    )
    assert missing.status_code == 403
    assert "No authority evidence was recorded" in missing.text

    cross_origin = _post(
        client,
        "/authority/workbench/requests",
        valid,
        Origin="http://attacker.invalid",
    )
    assert cross_origin.status_code == 403

    null_origin = _post(
        client,
        "/authority/workbench/requests",
        valid,
        Origin="null",
    )
    assert null_origin.status_code == 403

    cross_origin_oversize = client.post(
        "/authority/workbench/requests",
        content=b"padding=" + (b"x" * 9_000),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "http://attacker.invalid",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert cross_origin_oversize.status_code == 403

    with TestClient(
        create_app(_container), base_url=_BASE_URL, client=("127.0.0.1", 50_001)
    ) as other_client:
        _form_token(other_client, "/authority/workbench/requests/new")
        cross_session = _post(
            other_client,
            "/authority/workbench/requests",
            _request_form(token),
        )
    assert cross_session.status_code == 403

    created = _post(client, "/authority/workbench/requests", valid)
    replay = _post(client, "/authority/workbench/requests", valid)
    assert created.status_code == 303
    assert replay.status_code == 403


def test_workbench_validates_form_type_confirmation_and_safe_errors(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    token = _form_token(client, "/authority/workbench/requests/new")
    missing_confirmation = _post(
        client,
        "/authority/workbench/requests",
        _request_form(token, confirm=""),
    )
    assert missing_confirmation.status_code == 422
    assert "One or more submitted fields are invalid." in missing_confirmation.text

    token = _form_token(client, "/authority/workbench/requests/new")
    invalid_time = _post(
        client,
        "/authority/workbench/requests",
        _request_form(token, requested_at="not-a-timestamp"),
    )
    assert invalid_time.status_code == 422
    assert "not-a-timestamp" not in invalid_time.text

    wrong_content_type = client.post(
        "/authority/workbench/requests",
        content=b"{}",
        headers={**_ORIGIN_HEADERS, "Content-Type": "application/json"},
    )
    assert wrong_content_type.status_code == 422
    assert client.get("/api/authority/approval-requests").json()["items"] == []


def test_workbench_records_full_explicit_evidence_flow_without_execution(
    workbench_client: tuple[TestClient, AppContainer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _container = workbench_client
    monkeypatch.setattr(authority_router, "MAX_OPERATOR_PAGE_SIZE", 1)
    monkeypatch.setattr(authority_router, "DEFAULT_OPERATOR_PAGE_SIZE", 1)
    token = _form_token(client, "/authority/workbench/requests/new")
    created = _post(client, "/authority/workbench/requests", _request_form(token))
    assert created.status_code == 303
    assert created.headers["location"] == "/authority/workbench/requests/req-00000001"

    token = _form_token(client, "/authority/workbench/requests/req-00000001/decide")
    decided = _post(
        client,
        "/authority/workbench/requests/req-00000001/decide",
        _decision_form(token),
    )
    assert decided.status_code == 303

    token = _form_token(client, "/authority/workbench/requests/req-00000001/issue-grant")
    granted = _post(
        client,
        "/authority/workbench/requests/req-00000001/issue-grant",
        _grant_form(token),
    )
    assert granted.status_code == 303
    assert granted.headers["location"] == "/authority/workbench/grants/grant-00000001"

    token = _form_token(client, "/authority/workbench/grants/grant-00000001/evaluate")
    evaluated = _post(
        client,
        "/authority/workbench/grants/grant-00000001/evaluate",
        _evaluation_form(token),
    )
    assert evaluated.status_code == 303

    token = _form_token(client, "/authority/workbench/grants/grant-00000001/revoke")
    revoked = _post(
        client,
        "/authority/workbench/grants/grant-00000001/revoke",
        _revocation_form(token),
    )
    assert revoked.status_code == 303

    token = _form_token(client, "/authority/workbench/grants/grant-00000001/revoke")
    second_revocation = _post(
        client,
        "/authority/workbench/grants/grant-00000001/revoke",
        _revocation_form(
            token,
            revocation_id="rvk-00000002",
            effective_at="2026-07-22T00:00:00Z",
            recorded_at="2026-07-19T04:01:00Z",
            idempotency_key="revocation-key-02",
        ),
    )
    assert second_revocation.status_code == 303

    token = _form_token(client, "/authority/workbench/grants/grant-00000001/evaluate")
    revoked_evaluation = _post(
        client,
        "/authority/workbench/grants/grant-00000001/evaluate",
        _evaluation_form(
            token,
            evaluation_id="eval-00000002",
            evaluation_time="2026-07-21T00:00:00Z",
            idempotency_key="evaluation-key-02",
        ),
    )
    assert revoked_evaluation.status_code == 303

    detail = client.get("/authority/workbench/grants/grant-00000001")
    assert detail.status_code == 200
    assert "grant-00000001" in detail.text
    assert "rvk-00000001" in detail.text
    assert "eval-00000001" in detail.text
    assert "Older revocation evidence exists." in detail.text
    assert "Older evaluation evidence exists." in detail.text
    assert "not runtime enforcement" in detail.text
    assert ">Execute<" not in detail.text
    assert ">Run<" not in detail.text

    latest = client.get("/api/authority/grants/grant-00000001").json()["latest_evaluation"]
    assert latest["evaluation_id"] == "eval-00000002"
    assert latest["reason_code"] == "revoked"


def test_workbench_overview_labels_request_evidence_and_marks_each_list_truthfully(
    workbench_client: tuple[TestClient, AppContainer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _container = workbench_client
    monkeypatch.setattr(authority_router, "DEFAULT_OPERATOR_PAGE_SIZE", 1)

    _create_request(client)
    _record_decision(client)
    token = _form_token(client, "/authority/workbench/requests/req-00000001/issue-grant")
    assert (
        _post(
            client,
            "/authority/workbench/requests/req-00000001/issue-grant",
            _grant_form(token),
        ).status_code
        == 303
    )
    complete = client.get("/authority/workbench")
    assert "request recorded; inspect for lifecycle evidence" in complete.text
    assert ">pending<" not in complete.text
    assert "Older approval-request evidence exists." not in complete.text
    assert "Older capability-grant evidence exists." not in complete.text

    _create_request(
        client,
        request_id="req-00000002",
        idempotency_key="request-key-002",
    )
    token = _form_token(client, "/authority/workbench/requests/req-00000002/decide")
    assert (
        _post(
            client,
            "/authority/workbench/requests/req-00000002/decide",
            _decision_form(token, decision_id="dec-00000002", idempotency_key="decision-key-02"),
        ).status_code
        == 303
    )
    token = _form_token(client, "/authority/workbench/requests/req-00000002/issue-grant")
    assert (
        _post(
            client,
            "/authority/workbench/requests/req-00000002/issue-grant",
            _grant_form(
                token,
                decision_id="dec-00000002",
                grant_id="grant-00000002",
                idempotency_key="grant-key-002",
            ),
        ).status_code
        == 303
    )

    truncated = client.get("/authority/workbench")
    assert "Older approval-request evidence exists." in truncated.text
    assert "Older capability-grant evidence exists." in truncated.text
    assert truncated.text.index("Older approval-request evidence exists.") < truncated.text.index(
        'id="grants-heading"'
    )


def test_workbench_uses_one_cookie_namespace_and_keeps_camera_scope_distinct(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, container = workbench_client
    token = _form_token(client, "/authority/workbench/requests/new")
    assert token
    assert container.page_csrf_registry.active_session_count(PageCsrfScope.AUTHORITY_WORKBENCH) == 1
    assert container.camera_page_csrf_registry is None
    assert "OrbitMind-Camera" not in client.cookies


def test_workbench_renders_rejected_and_approved_ungranted_states(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    _create_request(client)
    _record_decision(client, outcome="rejected")

    rejected_detail = client.get("/authority/workbench/requests/req-00000001")
    unavailable_issue = client.get("/authority/workbench/requests/req-00000001/issue-grant")
    assert "stage: rejected" in rejected_detail.text
    assert "req-00000001/issue-grant" not in rejected_detail.text
    assert unavailable_issue.status_code == 409
    assert "A rejected decision cannot create a grant" in unavailable_issue.text


def test_workbench_renders_approved_ungranted_without_creating_a_grant(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    _create_request(client)
    _record_decision(client)

    detail = client.get("/authority/workbench/requests/req-00000001")
    issue_form = client.get("/authority/workbench/requests/req-00000001/issue-grant")
    grants = client.get("/api/authority/grants")
    assert detail.status_code == 200
    assert "stage: approved-ungranted" in detail.text
    # The detail page must surface the explicit issue-grant action, not only the
    # stage badge; issuing a grant is the one valid forward step at this stage.
    assert "req-00000001/issue-grant" in detail.text
    assert "no grant yet" in detail.text
    assert issue_form.status_code == 200
    assert grants.json()["items"] == []


def test_workbench_detail_surfaces_issue_grant_only_when_approved_ungranted(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    """The request-detail action panel offers the explicit issue-grant step
    exactly in the APPROVED_UNGRANTED stage — never in pending, rejected, or
    granted.

    Regression: an early ``if decisions:`` return once preempted the
    approved-ungranted branch, so an approved request exposed no Workbench path
    to issue its grant (the issue-grant affordance was unreachable dead code).
    """
    client, _container = workbench_client
    issue_grant_link = "req-00000001/issue-grant"

    # Pending: the record-decision action is offered; issue-grant is not yet valid.
    _create_request(client)
    pending_detail = client.get("/authority/workbench/requests/req-00000001")
    assert "stage: pending" in pending_detail.text
    assert issue_grant_link not in pending_detail.text
    assert "req-00000001/decide" in pending_detail.text

    # Approved-ungranted: the explicit issue-grant action is surfaced.
    _record_decision(client)
    approved_detail = client.get("/authority/workbench/requests/req-00000001")
    assert "stage: approved-ungranted" in approved_detail.text
    assert issue_grant_link in approved_detail.text
    assert "Issue grant" in approved_detail.text

    # Granted: the grant already exists, so no further request-level action shows.
    token = _form_token(client, "/authority/workbench/requests/req-00000001/issue-grant")
    granted = _post(
        client,
        "/authority/workbench/requests/req-00000001/issue-grant",
        _grant_form(token),
    )
    assert granted.status_code == 303
    granted_detail = client.get("/authority/workbench/requests/req-00000001")
    assert "stage: granted" in granted_detail.text
    assert issue_grant_link not in granted_detail.text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("requested_at", "not-a-timestamp"),
        ("requested_at", "2026-07-19T00:00:00"),
        ("scope_resource_type", "repository/escape"),
        ("idempotency_key", ""),
    ],
)
def test_workbench_rejects_invalid_form_values_without_persistence(
    workbench_client: tuple[TestClient, AppContainer], field: str, value: str
) -> None:
    client, _container = workbench_client
    token = _form_token(client, "/authority/workbench/requests/new")
    response = _post(
        client, "/authority/workbench/requests", _request_form(token, **{field: value})
    )
    assert response.status_code == 422
    assert client.get("/api/authority/approval-requests").json()["items"] == []


def test_workbench_escapes_stored_text_and_keeps_gets_non_mutating(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    assert client.get("/authority/workbench/requests/new").status_code == 200
    assert client.get("/api/authority/approval-requests").json()["items"] == []

    _create_request(client, purpose="<img src=x onerror=alert(1)>")
    detail = client.get("/authority/workbench/requests/req-00000001")
    assert "<img src=x onerror=alert(1)>" not in detail.text
    assert "&lt;img src=x onerror=alert(1)&gt;" in detail.text


def test_workbench_owner_isolation_and_no_execution_action(
    workbench_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = workbench_client
    _create_request(client)
    client.app.dependency_overrides[get_current_owner_id] = lambda: "other-owner"
    try:
        assert client.get("/authority/workbench/requests/req-00000001").status_code == 404
    finally:
        client.app.dependency_overrides.clear()

    presentation = (
        Path(__file__).resolve().parents[1] / "src/orbitmind/api/presentation/authority.py"
    ).read_text(encoding="utf-8")
    assert 'action="/run' not in presentation
    assert 'action="/execute' not in presentation
    assert ">Execute<" not in presentation
    assert ">Run<" not in presentation


def test_workbench_mutation_forms_are_post_only_and_never_accept_identity_fields() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "src/orbitmind/api/routers/authority.py").read_text(encoding="utf-8")
    presentation = (root / "src/orbitmind/api/presentation/authority.py").read_text(
        encoding="utf-8"
    )

    for route in (
        "/authority/workbench/requests",
        "/authority/workbench/requests/{request_id}/decide",
        "/authority/workbench/requests/{request_id}/issue-grant",
        "/authority/workbench/grants/{grant_id}/revoke",
        "/authority/workbench/grants/{grant_id}/evaluate",
    ):
        assert f'@router.post("{route}"' in source or f'@router.post(\n    "{route}"' in source
    assert 'name="owner_id"' not in presentation
    assert 'name="requested_by"' not in presentation
    assert 'name="decided_by"' not in presentation
    assert 'name="issued_by"' not in presentation
    assert 'name="revoked_by"' not in presentation
