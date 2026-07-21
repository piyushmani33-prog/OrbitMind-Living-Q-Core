"""U7.3 Authority Operator JSON API and Approval Workbench.

This router exposes the U7.2 authority lifecycle services through two surfaces:

1. ``/api/authority/*`` — trusted-local owner-scoped JSON endpoints. Mutations
   are append-only and idempotent; reads are bounded deterministic projections.
2. ``/authority/workbench/*`` — server-rendered HTML pages with explicit POST
   forms gated by the page-scoped CSRF registry.

Both surfaces derive ``owner_id`` and operator actor identity from the trusted
local operator context (see :mod:`orbitmind.api.deps`). No body or form field
may override either. The router performs **no** authority policy itself, runs
no tool, performs no operation, and emits no execution receipt. Every response
makes the authority distinctions explicit: request is not approval, approval is
not grant, grant is not execution, evaluation is evidence only.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape  # noqa: F401  (re-exported for templates that share this module)
from typing import Annotated, cast
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from orbitmind.api.authority_schemas import (
    ApprovalDecisionResponse,
    ApprovalRequestResponse,
    AuthorityChainResponse,
    AuthorityEvaluationResponse,
    BoundedApprovalRequestListResponse,
    BoundedCapabilityGrantListResponse,
    CapabilityGrantResponse,
    CreateApprovalRequestApiRequest,
    EvaluateAuthorityApiRequest,
    EvaluationListResponse,
    IssueCapabilityGrantApiRequest,
    RecordApprovalDecisionApiRequest,
    RevocationListResponse,
    RevocationResponse,
    RevokeCapabilityGrantApiRequest,
)
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container, get_current_owner_id
from orbitmind.api.presentation.authority import (
    AuthorityStage,
    render_decision_form,
    render_error_page,
    render_evaluate_form,
    render_grant_detail,
    render_issue_grant_form,
    render_new_request_form,
    render_overview,
    render_request_detail,
    render_revoke_form,
)
from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityReasonCode,
    AuthorityScope,
    CapabilityGrant,
    OperatorReference,
    SubjectReference,
    SubjectType,
)
from orbitmind.core.errors import (
    OrbitMindError,
    ValidationError,
)
from orbitmind.core.page_csrf import (
    AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
    AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME,
    AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_PATH,
    PAGE_CSRF_TTL_SECONDS,
    AuthorityWorkbenchCsrfRoute,
    PageCsrfProtocolAuthority,
    PageCsrfRejectedError,
    PageCsrfScope,
    PageSessionUnavailableError,
)
from orbitmind.orchestration.authority_lifecycle import (
    DEFAULT_OPERATOR_PAGE_SIZE,
    MAX_OPERATOR_PAGE_SIZE,
    AuthorityGrantNotFoundError,
    AuthorityLifecycleError,
    AuthorityRequestAlreadyDecidedError,
    AuthorityRequestNotFoundError,
    CreateApprovalRequestCommand,
    EvaluateAuthorityCommand,
    IssueCapabilityGrantCommand,
    RecordApprovalDecisionCommand,
    RevokeCapabilityGrantCommand,
    create_approval_request,
    evaluate_authority_command,
    issue_capability_grant,
    list_approval_decisions_for_request,
    list_approval_requests_bounded,
    list_capability_grants_bounded,
    list_evaluations_for_grant_bounded,
    list_revocations_for_grant_bounded,
    read_approval_request,
    read_approval_request_for_decision,
    read_authority_chain,
    read_capability_grant,
    read_evaluation_for_grant,
    read_latest_evaluation_for_grant,
    read_revocation_count_for_grant,
    read_revocation_for_grant,
    record_approval_decision,
    revoke_capability_grant,
)

_TRUSTED_LOCAL_AUTHORITY_PEER = "127.0.0.1"


def require_trusted_local_authority_peer(request: Request) -> None:
    """Reject Authority transport unless its direct TCP peer is canonical loopback."""

    client = request.client
    if client is None or client.host != _TRUSTED_LOCAL_AUTHORITY_PEER:
        raise HTTPException(
            status_code=403, detail="Authority routes require a local loopback peer"
        )


router = APIRouter(tags=["authority"], dependencies=[Depends(require_trusted_local_authority_peer)])


@dataclass(frozen=True, slots=True)
class TrustedLocalOperatorContext:
    """The explicit trusted-local boundary; not production authentication.

    The established owner dependency supplies the only owner value.  This local
    single-user context provides the matching fixed actor attribution and never
    accepts owner or actor identity from JSON, form, query, or route input.
    It conveys no remote identity assurance, multi-user authority, or privilege
    escalation and is deliberately an insertion point for future authentication.
    """

    owner_id: str
    operator_id: str = "local-operator"


def get_trusted_local_operator_context(
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> TrustedLocalOperatorContext:
    """Build the one trusted-local owner and actor context for Authority routes."""

    return TrustedLocalOperatorContext(owner_id=owner_id)


def get_authority_session(request: Request) -> Iterator[Session]:
    """Yield a per-request session for the U7.2 authority lifecycle services."""

    container = get_container(request)
    session = container.database.session()
    try:
        yield session
    finally:
        session.close()


ContainerDep = Annotated[AppContainer, Depends(get_container)]
OwnerDep = Annotated[str, Depends(get_current_owner_id)]
OperatorDep = Annotated[TrustedLocalOperatorContext, Depends(get_trusted_local_operator_context)]
SessionDep = Annotated[Session, Depends(get_authority_session)]

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
MAX_FORM_BODY_BYTES = 8_192
_REDIRECT_TARGET_MAXIMUM = 128


# ──────────────────────────────────────────────────────────────────────────
# JSON API — mutations
# ──────────────────────────────────────────────────────────────────────────


_MAX_AUTHORITY_API_BODY_BYTES = 16_384


async def _parse_json_body[ModelT: BaseModel](request: Request, model_type: type[ModelT]) -> ModelT:
    """Parse one bounded, strictly-typed JSON body in strict-JSON mode.

    FastAPI's default body injection validates in Python mode, where strict
    models reject ISO datetime strings and JSON arrays for tuples. Parsing the
    raw body with ``model_validate_json`` keeps the closed/coercion-free
    contract while accepting canonical JSON encodings. Content type and size
    are enforced before parsing; validation failures propagate to the
    registered sanitized 422 handler.
    """

    content_type = request.headers.get("content-type", "")
    if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
        raise ValidationError("authority API requires an application/json body")
    raw = await request.body()
    if len(raw) > _MAX_AUTHORITY_API_BODY_BYTES:
        raise ValidationError("authority API body exceeds the bounded size")
    return model_type.model_validate_json(raw)


def _created_or_replayed(*, status_code: int, payload: dict[str, object]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload, headers=dict(_NO_STORE_HEADERS))


@router.post("/api/authority/approval-requests")
async def create_approval_request_api(
    request: Request,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> JSONResponse:
    """Persist one non-authoritative approval request (201 first, 200 replay, 409 conflict)."""

    request_body = await _parse_json_body(request, CreateApprovalRequestApiRequest)

    command = CreateApprovalRequestCommand(
        owner_id=owner_id,
        request_id=request_body.request_id,
        requested_by=operator_id.operator_id,
        subject=request_body.subject,
        capability=request_body.capability,
        scope=request_body.scope,
        purpose=request_body.purpose,
        policy_version=request_body.policy_version,
        requested_at=request_body.requested_at,
        valid_from=request_body.valid_from,
        expires_at=request_body.expires_at,
        idempotency_key=request_body.idempotency_key,
    )
    status_code, stored = _run_mutation(
        session,
        lambda: create_approval_request(session=session, command=command),
        lambda: _read_request(session, owner_id, request_body.request_id) is not None,
    )
    response = ApprovalRequestResponse(request=stored)
    return _created_or_replayed(status_code=status_code, payload=response.model_dump(mode="json"))


@router.post("/api/authority/approval-requests/{request_id}/decisions")
async def record_decision_api(
    request_id: str,
    request: Request,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> JSONResponse:
    """Append one terminal decision (201 first, 200 replay, 409 conflict)."""

    request_body = await _parse_json_body(request, RecordApprovalDecisionApiRequest)

    command = RecordApprovalDecisionCommand(
        owner_id=owner_id,
        decision_id=request_body.decision_id,
        request_id=request_id,
        decided_by=OperatorReference(subject_id=operator_id.operator_id),
        outcome=request_body.outcome,
        decided_at=request_body.decided_at,
        reason=request_body.reason,
        policy_version=request_body.policy_version,
        idempotency_key=request_body.idempotency_key,
    )
    status_code, stored = _run_mutation(
        session,
        lambda: record_approval_decision(session=session, command=command),
        lambda: any(
            decision.decision_id == request_body.decision_id
            for decision in list_approval_decisions_for_request(
                session=session, owner_id=owner_id, request_id=request_id, limit=5
            )
        ),
    )
    response = ApprovalDecisionResponse(decision=stored)
    return _created_or_replayed(status_code=status_code, payload=response.model_dump(mode="json"))


@router.post("/api/authority/grants")
async def issue_grant_api(
    request: Request,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> JSONResponse:
    """Issue one grant from an approved decision (201 first, 200 replay, 409 conflict)."""

    request_body = await _parse_json_body(request, IssueCapabilityGrantApiRequest)

    stored_request = read_approval_request_for_decision(
        session=session, owner_id=owner_id, decision_id=request_body.decision_id
    )
    stored_window = stored_request.validity
    command = IssueCapabilityGrantCommand(
        owner_id=owner_id,
        grant_id=request_body.grant_id,
        request_id=stored_request.request_id,
        decision_id=request_body.decision_id,
        issued_by=OperatorReference(subject_id=operator_id.operator_id),
        issued_at=request_body.issued_at,
        valid_from=stored_window.valid_from,
        expires_at=stored_window.expires_at,
        policy_version=request_body.policy_version,
        idempotency_key=request_body.idempotency_key,
    )
    status_code, stored = _run_mutation(
        session,
        lambda: issue_capability_grant(session=session, command=command),
        lambda: _read_grant(session, owner_id, request_body.grant_id) is not None,
    )
    response = CapabilityGrantResponse(
        grant=stored,
        revocation_count=read_revocation_count_for_grant(
            session=session, owner_id=owner_id, grant_id=stored.grant_id
        ),
        latest_evaluation=read_latest_evaluation_for_grant(
            session=session, owner_id=owner_id, grant_id=stored.grant_id
        ),
    )
    return _created_or_replayed(status_code=status_code, payload=response.model_dump(mode="json"))


@router.post("/api/authority/grants/{grant_id}/revocations")
async def revoke_grant_api(
    grant_id: str,
    request: Request,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> JSONResponse:
    """Append one revocation (201 first, 200 replay, 409 conflict)."""

    request_body = await _parse_json_body(request, RevokeCapabilityGrantApiRequest)

    command = RevokeCapabilityGrantCommand(
        owner_id=owner_id,
        revocation_id=request_body.revocation_id,
        grant_id=grant_id,
        revoked_by=operator_id.operator_id,
        effective_at=request_body.effective_at,
        recorded_at=request_body.recorded_at,
        reason=request_body.reason,
        policy_version=request_body.policy_version,
        idempotency_key=request_body.idempotency_key,
    )
    status_code, stored = _run_mutation(
        session,
        lambda: revoke_capability_grant(session=session, command=command),
        lambda: (
            read_revocation_for_grant(
                session=session,
                owner_id=owner_id,
                grant_id=grant_id,
                revocation_id=request_body.revocation_id,
            )
            is not None
        ),
    )
    response = RevocationResponse(revocation=stored)
    return _created_or_replayed(status_code=status_code, payload=response.model_dump(mode="json"))


@router.post("/api/authority/evaluations")
async def evaluate_authority_api(
    request: Request,
    owner_id: OwnerDep,
    session: SessionDep,
) -> JSONResponse:
    """Persist one grant-backed evaluation (201 first, 200 replay, 409 conflict)."""

    request_body = await _parse_json_body(request, EvaluateAuthorityApiRequest)

    grant = _read_grant(session, owner_id, request_body.grant_id)
    if grant is None:
        raise AuthorityGrantNotFoundError("authority capability grant was not found")
    command = EvaluateAuthorityCommand(
        owner_id=owner_id,
        evaluation_id=request_body.evaluation_id,
        request_id=grant.request_id,
        decision_id=grant.decision_id,
        grant_id=grant.grant_id,
        subject=grant.subject,
        capability=grant.capability,
        scope=grant.scope,
        purpose=grant.purpose,
        evaluation_time=request_body.evaluation_time,
        delegation_requested=request_body.delegation_requested,
        policy_version=request_body.policy_version,
        idempotency_key=request_body.idempotency_key,
    )
    status_code, stored = _run_mutation(
        session,
        lambda: evaluate_authority_command(session=session, command=command),
        lambda: (
            read_evaluation_for_grant(
                session=session,
                owner_id=owner_id,
                grant_id=request_body.grant_id,
                evaluation_id=request_body.evaluation_id,
            )
            is not None
        ),
    )
    response = AuthorityEvaluationResponse(evaluation=stored)
    return _created_or_replayed(status_code=status_code, payload=response.model_dump(mode="json"))


# ──────────────────────────────────────────────────────────────────────────
# JSON API — reads
# ──────────────────────────────────────────────────────────────────────────


@router.get("/api/authority/approval-requests/{request_id}")
def read_approval_request_api(
    request_id: str, owner_id: OwnerDep, session: SessionDep
) -> JSONResponse:
    request = _read_request(session, owner_id, request_id)
    if request is None:
        raise AuthorityRequestNotFoundError("authority approval request was not found")
    response = ApprovalRequestResponse(request=request)
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


@router.get("/api/authority/approval-requests/{request_id}/chain")
def read_authority_chain_api(
    request_id: str, owner_id: OwnerDep, session: SessionDep
) -> JSONResponse:
    chain = read_authority_chain(session=session, owner_id=owner_id, request_id=request_id)
    if chain is None:
        raise AuthorityRequestNotFoundError("authority approval request was not found")
    response = AuthorityChainResponse(
        owner_id=chain.owner_id,
        approval_request=chain.approval_request,
        approval_decisions=chain.approval_decisions,
        capability_grants=chain.capability_grants,
        revocations=chain.revocations,
        evaluations=chain.evaluations,
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


@router.get("/api/authority/grants/{grant_id}")
def read_grant_api(grant_id: str, owner_id: OwnerDep, session: SessionDep) -> JSONResponse:
    grant = _read_grant(session, owner_id, grant_id)
    if grant is None:
        raise AuthorityGrantNotFoundError("authority capability grant was not found")
    response = CapabilityGrantResponse(
        grant=grant,
        revocation_count=read_revocation_count_for_grant(
            session=session, owner_id=owner_id, grant_id=grant_id
        ),
        latest_evaluation=read_latest_evaluation_for_grant(
            session=session, owner_id=owner_id, grant_id=grant_id
        ),
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


@router.get("/api/authority/grants/{grant_id}/revocations")
def list_revocations_api(
    grant_id: str,
    owner_id: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_OPERATOR_PAGE_SIZE)] = MAX_OPERATOR_PAGE_SIZE,
) -> JSONResponse:
    if _read_grant(session, owner_id, grant_id) is None:
        raise AuthorityGrantNotFoundError("authority capability grant was not found")
    page_probe = list_revocations_for_grant_bounded(
        session=session, owner_id=owner_id, grant_id=grant_id, limit=limit + 1
    )
    items = page_probe[:limit]
    response = RevocationListResponse(
        owner_id=owner_id,
        grant_id=grant_id,
        items=items,
        page_size=len(items),
        truncated=len(page_probe) > limit,
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


@router.get("/api/authority/grants/{grant_id}/evaluations")
def list_evaluations_api(
    grant_id: str,
    owner_id: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_OPERATOR_PAGE_SIZE)] = DEFAULT_OPERATOR_PAGE_SIZE,
) -> JSONResponse:
    if _read_grant(session, owner_id, grant_id) is None:
        raise AuthorityGrantNotFoundError("authority capability grant was not found")
    page_probe = list_evaluations_for_grant_bounded(
        session=session, owner_id=owner_id, grant_id=grant_id, limit=limit + 1
    )
    items = page_probe[:limit]
    response = EvaluationListResponse(
        owner_id=owner_id,
        grant_id=grant_id,
        items=items,
        page_size=len(items),
        truncated=len(page_probe) > limit,
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


@router.get("/api/authority/approval-requests")
def list_approval_requests_api(
    owner_id: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_OPERATOR_PAGE_SIZE)] = DEFAULT_OPERATOR_PAGE_SIZE,
) -> JSONResponse:
    page_probe = list_approval_requests_bounded(session=session, owner_id=owner_id, limit=limit + 1)
    items = page_probe[:limit]
    response = BoundedApprovalRequestListResponse(
        owner_id=owner_id, items=items, page_size=len(items), truncated=len(page_probe) > limit
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


@router.get("/api/authority/grants")
def list_grants_api(
    owner_id: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_OPERATOR_PAGE_SIZE)] = DEFAULT_OPERATOR_PAGE_SIZE,
) -> JSONResponse:
    page_probe = list_capability_grants_bounded(session=session, owner_id=owner_id, limit=limit + 1)
    items = page_probe[:limit]
    response = BoundedCapabilityGrantListResponse(
        owner_id=owner_id, items=items, page_size=len(items), truncated=len(page_probe) > limit
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=dict(_NO_STORE_HEADERS))


def _read_request(session: Session, owner_id: str, request_id: str) -> ApprovalRequest | None:
    return read_approval_request(session=session, owner_id=owner_id, request_id=request_id)


def _read_grant(session: Session, owner_id: str, grant_id: str) -> CapabilityGrant | None:
    return read_capability_grant(session=session, owner_id=owner_id, grant_id=grant_id)


# ──────────────────────────────────────────────────────────────────────────
# Helpers: bounded grant-issue / evaluate chain reads, mutation runner,
# CSRF, form parsing, redirects, error pages.
# ──────────────────────────────────────────────────────────────────────────


def _run_mutation[ResultT](
    session: Session,
    operation: Callable[[], ResultT],
    already_exists: Callable[[], bool],
) -> tuple[int, ResultT]:
    """Run one append: 201 for a fresh record, 200 for an identical replay.

    ``already_exists`` probes for the exact record id through the lifecycle
    read surface before the append. The U7.2 services resolve idempotent
    replays by returning the stored record, and conflicting replays raise
    ``IdempotencyConflictError`` (409 via the global handler), so a pre-existing
    record combined with a successful append is exactly an identical replay.
    """

    existed = already_exists()
    result = operation()
    return (200 if existed else 201), result


# ──────────────────────────────────────────────────────────────────────────
# Workbench — read-only pages
# ──────────────────────────────────────────────────────────────────────────


@router.get("/authority/workbench", response_class=HTMLResponse)
def workbench_overview(
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    """Render the Workbench overview with bounded owner-scoped evidence."""

    request_probe = list_approval_requests_bounded(
        session=session, owner_id=owner_id, limit=DEFAULT_OPERATOR_PAGE_SIZE + 1
    )
    grant_probe = list_capability_grants_bounded(
        session=session, owner_id=owner_id, limit=DEFAULT_OPERATOR_PAGE_SIZE + 1
    )
    requests = request_probe[:DEFAULT_OPERATOR_PAGE_SIZE]
    grants = grant_probe[:DEFAULT_OPERATOR_PAGE_SIZE]
    page = render_overview(
        owner_id=owner_id,
        requests=requests,
        grants=grants,
        page_size=DEFAULT_OPERATOR_PAGE_SIZE,
        requests_truncated=len(request_probe) > DEFAULT_OPERATOR_PAGE_SIZE,
        grants_truncated=len(grant_probe) > DEFAULT_OPERATOR_PAGE_SIZE,
    )
    response = HTMLResponse(content=page, headers=dict(_NO_STORE_HEADERS))
    return response


@router.get("/authority/workbench/requests/new", response_class=HTMLResponse)
def workbench_new_request_form(
    container: ContainerDep,
    owner_id: OwnerDep,
    request: Request,
) -> HTMLResponse:
    """Render the new-approval-request form with a page-scoped CSRF token."""

    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_new_request_form(csrf_token=csrf_token, owner_id=owner_id)
    return _form_response(page, page_session_id)


@router.get(
    "/authority/workbench/requests/{request_id}",
    response_class=HTMLResponse,
)
def workbench_request_detail(
    request_id: str,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    chain = read_authority_chain(session=session, owner_id=owner_id, request_id=request_id)
    if chain is None:
        return _workbench_not_found("Approval request not found")
    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_request_detail(
        owner_id=owner_id,
        request=chain.approval_request,
        decisions=chain.approval_decisions,
        grants=chain.capability_grants,
        revocations=chain.revocations,
        evaluations=chain.evaluations,
        csrf_token=csrf_token,
    )
    return _form_response(page, page_session_id)


@router.get(
    "/authority/workbench/requests/{request_id}/decide",
    response_class=HTMLResponse,
)
def workbench_decision_form(
    request_id: str,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    chain = read_authority_chain(session=session, owner_id=owner_id, request_id=request_id)
    if chain is None:
        return _workbench_not_found("Approval request not found")
    if chain.approval_decisions:
        return _workbench_conflict(
            "This request already has a terminal decision. A second terminal decision "
            "would be rejected as an immutable-evidence conflict."
        )
    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_decision_form(request=chain.approval_request, csrf_token=csrf_token)
    return _form_response(page, page_session_id)


@router.get(
    "/authority/workbench/requests/{request_id}/issue-grant",
    response_class=HTMLResponse,
)
def workbench_issue_grant_form(
    request_id: str,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    chain = read_authority_chain(session=session, owner_id=owner_id, request_id=request_id)
    if chain is None:
        return _workbench_not_found("Approval request not found")
    if not chain.approval_decisions:
        return _workbench_conflict(
            "This request has no terminal decision yet; a grant cannot be issued."
        )
    decision = chain.approval_decisions[0]
    if decision.outcome is ApprovalDecisionOutcome.REJECTED:
        return _workbench_conflict(
            "A rejected decision cannot create a grant. Issue-grant is unavailable."
        )
    if chain.capability_grants:
        return _workbench_conflict(
            "This request already has an issued grant; a second grant is unavailable."
        )
    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_issue_grant_form(
        request=chain.approval_request, decision=decision, csrf_token=csrf_token
    )
    return _form_response(page, page_session_id)


@router.get(
    "/authority/workbench/grants/{grant_id}",
    response_class=HTMLResponse,
)
def workbench_grant_detail(
    grant_id: str,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    grant = _read_grant(session, owner_id, grant_id)
    if grant is None:
        return _workbench_not_found("Capability grant not found")
    revocation_probe = list_revocations_for_grant_bounded(
        session=session,
        owner_id=owner_id,
        grant_id=grant_id,
        limit=MAX_OPERATOR_PAGE_SIZE + 1,
    )
    evaluation_page_size = DEFAULT_OPERATOR_PAGE_SIZE
    evaluation_probe = list_evaluations_for_grant_bounded(
        session=session,
        owner_id=owner_id,
        grant_id=grant_id,
        limit=evaluation_page_size + 1,
    )
    revocations = revocation_probe[:MAX_OPERATOR_PAGE_SIZE]
    evaluations = evaluation_probe[:evaluation_page_size]
    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_grant_detail(
        owner_id=owner_id,
        grant=grant,
        revocations=revocations,
        evaluations=evaluations,
        revocations_truncated=len(revocation_probe) > MAX_OPERATOR_PAGE_SIZE,
        evaluations_truncated=len(evaluation_probe) > evaluation_page_size,
        csrf_token=csrf_token,
    )
    return _form_response(page, page_session_id)


@router.get(
    "/authority/workbench/grants/{grant_id}/revoke",
    response_class=HTMLResponse,
)
def workbench_revoke_form_route(
    grant_id: str,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    grant = _read_grant(session, owner_id, grant_id)
    if grant is None:
        return _workbench_not_found("Capability grant not found")
    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_revoke_form(grant=grant, csrf_token=csrf_token)
    return _form_response(page, page_session_id)


@router.get(
    "/authority/workbench/grants/{grant_id}/evaluate",
    response_class=HTMLResponse,
)
def workbench_evaluate_form_route(
    grant_id: str,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
    request: Request,
) -> HTMLResponse:
    grant = _read_grant(session, owner_id, grant_id)
    if grant is None:
        return _workbench_not_found("Capability grant not found")
    csrf_token, page_session_id = _issue_form_authority(request, container)
    page = render_evaluate_form(grant=grant, csrf_token=csrf_token)
    return _form_response(page, page_session_id)


# ──────────────────────────────────────────────────────────────────────────
# Workbench — POST mutations (CSRF-gated, POST-only)
# ──────────────────────────────────────────────────────────────────────────


@router.post("/authority/workbench/requests", response_class=HTMLResponse)
async def workbench_create_request(
    request: Request,
    container: ContainerDep,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> Response:
    try:
        preflight = _enforce_workbench_protocol(
            request, container, AuthorityWorkbenchCsrfRoute.CREATE_REQUEST
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        form = await _parse_form(
            request,
            {
                AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
                "confirm",
                "request_id",
                "subject_type",
                "subject_id",
                "capability",
                "scope_resource_type",
                "scope_resource_id",
                "purpose",
                "policy_version",
                "requested_at",
                "valid_from",
                "expires_at",
                "idempotency_key",
            },
        )
    except AuthorityLifecycleError:
        return _workbench_validation_error("The submitted form is invalid.")
    try:
        _enforce_workbench_csrf(
            request,
            container,
            AuthorityWorkbenchCsrfRoute.CREATE_REQUEST,
            preflight,
            csrf_token_values=(form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD],)
            if form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD]
            else (),
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        _require_confirmation(form)
        command = CreateApprovalRequestCommand(
            owner_id=owner_id,
            request_id=form["request_id"],
            requested_by=operator_id.operator_id,
            subject=SubjectReference(
                subject_type=SubjectType(form["subject_type"]),
                subject_id=form["subject_id"],
            ),
            capability=form["capability"],
            scope=_scope_from_form(form),
            purpose=form["purpose"],
            policy_version=form["policy_version"],
            requested_at=_parse_utc(form["requested_at"], "requested_at"),
            valid_from=_parse_utc(form["valid_from"], "valid_from"),
            expires_at=_parse_utc(form["expires_at"], "expires_at"),
            idempotency_key=form["idempotency_key"],
        )
        stored = create_approval_request(session=session, command=command)
    except PydanticValidationError as error:
        return _workbench_validation_error(str(_first_error(error)))
    except ValueError as error:
        return _workbench_validation_error(_safe_validation_message(error))
    except OrbitMindError as error:
        return _workbench_orbital_error(error)
    return RedirectResponse(
        url=_safe_redirect(f"/authority/workbench/requests/{stored.request_id}"),
        status_code=303,
    )


@router.post(
    "/authority/workbench/requests/{request_id}/decide",
    response_class=HTMLResponse,
)
async def workbench_record_decision(
    request_id: str,
    request: Request,
    container: ContainerDep,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> Response:
    try:
        preflight = _enforce_workbench_protocol(
            request, container, AuthorityWorkbenchCsrfRoute.RECORD_DECISION
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        form = await _parse_form(
            request,
            {
                AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
                "confirm",
                "decision_id",
                "outcome",
                "decided_at",
                "reason",
                "policy_version",
                "idempotency_key",
            },
        )
    except AuthorityLifecycleError:
        return _workbench_validation_error("The submitted form is invalid.")
    try:
        _enforce_workbench_csrf(
            request,
            container,
            AuthorityWorkbenchCsrfRoute.RECORD_DECISION,
            preflight,
            csrf_token_values=(form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD],)
            if form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD]
            else (),
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        _require_confirmation(form)
        command = RecordApprovalDecisionCommand(
            owner_id=owner_id,
            decision_id=form["decision_id"],
            request_id=request_id,
            decided_by=OperatorReference(subject_id=operator_id.operator_id),
            outcome=ApprovalDecisionOutcome(form["outcome"]),
            decided_at=_parse_utc(form["decided_at"], "decided_at"),
            reason=form["reason"],
            policy_version=form["policy_version"],
            idempotency_key=form["idempotency_key"],
        )
        record_approval_decision(session=session, command=command)
    except PydanticValidationError as error:
        return _workbench_validation_error(str(_first_error(error)))
    except ValueError as error:
        return _workbench_validation_error(_safe_validation_message(error))
    except OrbitMindError as error:
        return _workbench_orbital_error(error)
    return RedirectResponse(
        url=_safe_redirect(f"/authority/workbench/requests/{request_id}"),
        status_code=303,
    )


@router.post(
    "/authority/workbench/requests/{request_id}/issue-grant",
    response_class=HTMLResponse,
)
async def workbench_issue_grant(
    request_id: str,
    request: Request,
    container: ContainerDep,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> Response:
    try:
        preflight = _enforce_workbench_protocol(
            request, container, AuthorityWorkbenchCsrfRoute.ISSUE_GRANT
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        form = await _parse_form(
            request,
            {
                AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
                "confirm",
                "decision_id",
                "grant_id",
                "issued_at",
                "policy_version",
                "idempotency_key",
            },
        )
    except AuthorityLifecycleError:
        return _workbench_validation_error("The submitted form is invalid.")
    try:
        _enforce_workbench_csrf(
            request,
            container,
            AuthorityWorkbenchCsrfRoute.ISSUE_GRANT,
            preflight,
            csrf_token_values=(form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD],)
            if form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD]
            else (),
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        _require_confirmation(form)
        stored_request = read_approval_request_for_decision(
            session=session, owner_id=owner_id, decision_id=form["decision_id"]
        )
        if stored_request.request_id != request_id:
            return _workbench_validation_error(
                "The selected decision does not belong to this request."
            )
        command = IssueCapabilityGrantCommand(
            owner_id=owner_id,
            grant_id=form["grant_id"],
            request_id=request_id,
            decision_id=form["decision_id"],
            issued_by=OperatorReference(subject_id=operator_id.operator_id),
            issued_at=_parse_utc(form["issued_at"], "issued_at"),
            valid_from=stored_request.validity.valid_from,
            expires_at=stored_request.validity.expires_at,
            policy_version=form["policy_version"],
            idempotency_key=form["idempotency_key"],
        )
        stored = issue_capability_grant(session=session, command=command)
    except PydanticValidationError as error:
        return _workbench_validation_error(str(_first_error(error)))
    except ValueError as error:
        return _workbench_validation_error(_safe_validation_message(error))
    except OrbitMindError as error:
        return _workbench_orbital_error(error)
    return RedirectResponse(
        url=_safe_redirect(f"/authority/workbench/grants/{stored.grant_id}"),
        status_code=303,
    )


@router.post(
    "/authority/workbench/grants/{grant_id}/revoke",
    response_class=HTMLResponse,
)
async def workbench_revoke_grant(
    grant_id: str,
    request: Request,
    container: ContainerDep,
    owner_id: OwnerDep,
    operator_id: OperatorDep,
    session: SessionDep,
) -> Response:
    try:
        preflight = _enforce_workbench_protocol(
            request, container, AuthorityWorkbenchCsrfRoute.REVOKE_GRANT
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        form = await _parse_form(
            request,
            {
                AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
                "confirm",
                "revocation_id",
                "effective_at",
                "recorded_at",
                "reason",
                "policy_version",
                "idempotency_key",
            },
        )
    except AuthorityLifecycleError:
        return _workbench_validation_error("The submitted form is invalid.")
    try:
        _enforce_workbench_csrf(
            request,
            container,
            AuthorityWorkbenchCsrfRoute.REVOKE_GRANT,
            preflight,
            csrf_token_values=(form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD],)
            if form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD]
            else (),
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        _require_confirmation(form)
        command = RevokeCapabilityGrantCommand(
            owner_id=owner_id,
            revocation_id=form["revocation_id"],
            grant_id=grant_id,
            revoked_by=operator_id.operator_id,
            effective_at=_parse_utc(form["effective_at"], "effective_at"),
            recorded_at=_parse_utc(form["recorded_at"], "recorded_at"),
            reason=form["reason"],
            policy_version=form["policy_version"],
            idempotency_key=form["idempotency_key"],
        )
        revoke_capability_grant(session=session, command=command)
    except PydanticValidationError as error:
        return _workbench_validation_error(str(_first_error(error)))
    except ValueError as error:
        return _workbench_validation_error(_safe_validation_message(error))
    except OrbitMindError as error:
        return _workbench_orbital_error(error)
    return RedirectResponse(
        url=_safe_redirect(f"/authority/workbench/grants/{grant_id}"),
        status_code=303,
    )


@router.post(
    "/authority/workbench/grants/{grant_id}/evaluate",
    response_class=HTMLResponse,
)
async def workbench_evaluate_grant(
    grant_id: str,
    request: Request,
    container: ContainerDep,
    owner_id: OwnerDep,
    session: SessionDep,
) -> Response:
    try:
        preflight = _enforce_workbench_protocol(
            request, container, AuthorityWorkbenchCsrfRoute.EVALUATE_GRANT
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    try:
        form = await _parse_form(
            request,
            {
                AUTHORITY_WORKBENCH_CSRF_FORM_FIELD,
                "confirm",
                "evaluation_id",
                "evaluation_time",
                "policy_version",
                "delegation_requested",
                "idempotency_key",
            },
        )
    except AuthorityLifecycleError:
        return _workbench_validation_error("The submitted form is invalid.")
    try:
        _enforce_workbench_csrf(
            request,
            container,
            AuthorityWorkbenchCsrfRoute.EVALUATE_GRANT,
            preflight,
            csrf_token_values=(form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD],)
            if form[AUTHORITY_WORKBENCH_CSRF_FORM_FIELD]
            else (),
        )
    except PageCsrfRejectedError:
        return _workbench_csrf_rejected()
    grant = _read_grant(session, owner_id, grant_id)
    if grant is None:
        return _workbench_not_found("Capability grant not found")
    try:
        _require_confirmation(form)
        command = EvaluateAuthorityCommand(
            owner_id=owner_id,
            evaluation_id=form["evaluation_id"],
            request_id=grant.request_id,
            decision_id=grant.decision_id,
            grant_id=grant.grant_id,
            subject=grant.subject,
            capability=grant.capability,
            scope=grant.scope,
            purpose=grant.purpose,
            evaluation_time=_parse_utc(form["evaluation_time"], "evaluation_time"),
            delegation_requested=_parse_boolean_form(
                form["delegation_requested"], "delegation_requested"
            ),
            policy_version=form["policy_version"],
            idempotency_key=form["idempotency_key"],
        )
        evaluate_authority_command(session=session, command=command)
    except PydanticValidationError as error:
        return _workbench_validation_error(str(_first_error(error)))
    except ValueError as error:
        return _workbench_validation_error(_safe_validation_message(error))
    except OrbitMindError as error:
        return _workbench_orbital_error(error)
    return RedirectResponse(
        url=_safe_redirect(f"/authority/workbench/grants/{grant_id}"),
        status_code=303,
    )


# ──────────────────────────────────────────────────────────────────────────
# Helpers: mutation runner, form parsing, redirects, error pages.
# ──────────────────────────────────────────────────────────────────────────


def _scope_from_form(form: dict[str, str]) -> AuthorityScope:
    return AuthorityScope(
        resource_type=form["scope_resource_type"],
        resource_id=form["scope_resource_id"],
    )


def _parse_utc(value: str, field_name: str) -> datetime:
    raw = value.strip()
    if len(raw) > 40:
        raise ValueError(f"{field_name} is invalid")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit UTC offset")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC (Z or +00:00)")
    return parsed.astimezone(UTC)


def _safe_validation_message(error: ValueError) -> str:
    """Keep local form conversion failures deterministic and non-disclosing."""

    del error
    return "One or more submitted fields are invalid."


def _parse_boolean_form(value: str, field_name: str) -> bool:
    """Accept the two explicit boolean form encodings and reject all others."""

    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"{field_name} must be true or false")


def _require_confirmation(form: dict[str, str]) -> None:
    """Require one explicit checked confirmation for every Workbench mutation."""

    if form.get("confirm") != "yes":
        raise ValueError("action confirmation is required")


def _first_error(error: PydanticValidationError) -> str:
    if not error.errors():
        return "request failed domain validation"
    first = error.errors()[0]
    loc = ".".join(str(part) for part in first.get("loc", ()))
    return f"{loc}: {first.get('msg', 'invalid')}" if loc else first.get("msg", "invalid")


def _workbench_not_found(message: str) -> HTMLResponse:
    page = render_error_page(title="Not found", message=message)
    return HTMLResponse(content=page, status_code=404, headers=dict(_NO_STORE_HEADERS))


def _workbench_conflict(message: str) -> HTMLResponse:
    page = render_error_page(title="Action unavailable", message=message)
    return HTMLResponse(content=page, status_code=409, headers=dict(_NO_STORE_HEADERS))


def _workbench_csrf_rejected() -> HTMLResponse:
    """Sanitized 403 page for a rejected Workbench form submission."""

    page = render_error_page(
        title="Form submission rejected",
        message=(
            "The form's CSRF protection rejected this submission. Reload the "
            "form page and try again. No authority evidence was recorded."
        ),
    )
    return HTMLResponse(content=page, status_code=403, headers=dict(_NO_STORE_HEADERS))


def _workbench_validation_error(message: str) -> HTMLResponse:
    page = render_error_page(title="Validation error", message=message)
    return HTMLResponse(content=page, status_code=422, headers=dict(_NO_STORE_HEADERS))


def _workbench_orbital_error(error: OrbitMindError) -> HTMLResponse:
    page = render_error_page(title="Request rejected", message=error.message)
    status_code = (
        409 if isinstance(error, AuthorityRequestAlreadyDecidedError) else error.http_status
    )
    return HTMLResponse(content=page, status_code=status_code, headers=dict(_NO_STORE_HEADERS))


def _safe_redirect(target: str) -> str:
    """Confine a POST/Redirect/GET target to the Workbench prefix."""

    if not target.startswith("/authority/workbench/") or len(target) > _REDIRECT_TARGET_MAXIMUM:
        return "/authority/workbench"
    return target


async def _parse_form(request: Request, allowed_fields: set[str]) -> dict[str, str]:
    """Bounded, strict form parsing mirroring review/workbench conventions."""

    content_type = request.headers.get("content-type", "")
    if (
        content_type.split(";", maxsplit=1)[0].strip().lower()
        != "application/x-www-form-urlencoded"
    ):
        raise AuthorityLifecycleError("authority form requires form-url-encoded content")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_FORM_BODY_BYTES:
            raise AuthorityLifecycleError("authority form body exceeds the supported size")
    try:
        decoded = bytes(body).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthorityLifecycleError("authority form must be UTF-8 encoded") from exc
    try:
        parsed = parse_qs(decoded, keep_blank_values=True, max_num_fields=len(allowed_fields) + 1)
    except ValueError as exc:
        raise AuthorityLifecycleError("authority form could not be parsed safely") from exc
    if set(parsed) - allowed_fields:
        raise AuthorityLifecycleError("authority form contains an unexpected field")
    result: dict[str, str] = {}
    for field in allowed_fields:
        values = parsed.get(field, [])
        if len(values) > 1:
            raise AuthorityLifecycleError(f"authority form field {field} must be supplied once")
        result[field] = values[0].strip() if values else ""
    return result


def _enforce_workbench_csrf(
    request: Request,
    container: AppContainer,
    route: AuthorityWorkbenchCsrfRoute,
    preflight: object,
    csrf_token_values: tuple[str, ...],
) -> None:
    """Validate Workbench CSRF + same-origin authority for one mutating form POST.

    ``csrf_token_values`` comes from the parsed form body (HTML forms cannot
    set custom request headers); an absent or blank token fails closed.
    """

    registry = container.require_page_csrf_registry()
    try:
        registry.validate_and_rotate_after_preflight(
            preflight,
            expected_scope=PageCsrfScope.AUTHORITY_WORKBENCH,
            expected_route=route,
            page_session_cookie=request.cookies.get(AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME),
            csrf_token_values=csrf_token_values,
        )
    except PageSessionUnavailableError as exc:
        raise PageCsrfRejectedError from exc


def _enforce_workbench_protocol(
    request: Request,
    container: AppContainer,
    route: AuthorityWorkbenchCsrfRoute,
) -> object:
    """Validate same-origin protocol inputs before consuming a Workbench form body."""

    registry = container.require_page_csrf_registry()
    protocol = _protocol_authority(request, container.settings.custom_tle_handoff_port, route)
    try:
        return registry.validate_protocol_preflight(protocol)
    except PageSessionUnavailableError as exc:
        raise PageCsrfRejectedError from exc


def _protocol_authority(
    request: Request, port: int, route: AuthorityWorkbenchCsrfRoute
) -> PageCsrfProtocolAuthority:
    return PageCsrfProtocolAuthority(
        scope=PageCsrfScope.AUTHORITY_WORKBENCH,
        method=request.method,
        route=route,
        scheme=request.url.scheme,
        host_values=_header_values(request, "Host"),
        origin_values=_header_values(request, "Origin"),
        sec_fetch_site_values=_header_values(request, "Sec-Fetch-Site"),
        forwarded_header_names=_forwarded_header_names(request),
        selected_port=port,
    )


def _header_values(request: Request, name: str) -> tuple[str, ...]:
    expected = name.casefold().encode("ascii")
    headers = cast(list[tuple[bytes, bytes]], request.scope.get("headers", []))
    return tuple(value.decode("latin-1") for key, value in headers if key.lower() == expected)


def _forwarded_header_names(request: Request) -> tuple[str, ...]:
    headers = cast(list[tuple[bytes, bytes]], request.scope.get("headers", []))
    return tuple(
        key.decode("latin-1")
        for key, _value in headers
        if key.lower() == b"forwarded" or key.lower().startswith(b"x-forwarded-")
    )


def _issue_form_authority(request: Request, container: AppContainer) -> tuple[str, str | None]:
    """Issue ONE page session per rendered form: ``(csrf_token, page_session_id)``.

    The token rendered into the form and the page-session cookie set on the
    same response always come from this single issuance, so they can never
    desynchronize. Returns ``("", None)`` when issuance is unavailable; the
    form renders with an empty token and no cookie is set (POSTs then fail
    closed at CSRF validation).
    """

    try:
        issued = container.require_page_csrf_registry().issue(
            PageCsrfScope.AUTHORITY_WORKBENCH,
            request.cookies.get(AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME),
        )
    except PageSessionUnavailableError:
        return "", None
    return issued.csrf_token, issued.page_session_id


def _form_response(page: str, page_session_id: str | None) -> HTMLResponse:
    """Build a no-store HTML response carrying the matching page-session cookie."""

    response = HTMLResponse(content=page, headers=dict(_NO_STORE_HEADERS))
    if page_session_id is not None:
        response.set_cookie(
            key=AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME,
            value=page_session_id,
            max_age=PAGE_CSRF_TTL_SECONDS,
            path=AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_PATH,
            secure=False,
            httponly=True,
            samesite="strict",
        )
    return response


# Re-export for the architecture tests.
__all__ = [
    "ApprovalDecision",
    "AuthorityReasonCode",
    "AuthorityStage",
    "router",
]
