"""Strict API request/response DTOs for the U7.3 authority operator surface.

Request DTOs are closed, immutable, coercion-free, and never accept owner or
actor identity from the request body: those values come from the trusted
authenticated operator context (see ``api.deps``). They mirror the U7.2
command semantics so a request DTO can be projected into a lifecycle command
without re-interpretation.

Response DTOs are deterministic projections of stored U7.0 contract evidence.
They never include SQLAlchemy rows, callables, credentials, internal record
keys, or filesystem paths. Every response makes the U7 authority distinctions
visible: request is non-authoritative, approval is not a grant, grant is not
execution, and an evaluation is evidence only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityEvaluationDecision,
    AuthorityScope,
    CapabilityGrant,
    RevocationRecord,
    SubjectReference,
)

AUTHORITY_API_SCHEMA_VERSION: Literal["authority-api-v1"] = "authority-api-v1"

_ID_FIELD = Field(pattern=r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$")
_POLICY_FIELD = Field(pattern=r"^[a-z][a-z0-9.-]{2,63}$")
_CAPABILITY_FIELD = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
_IDEMPOTENCY_FIELD = Field(min_length=1, max_length=200)
_PURPOSE_FIELD = Field(min_length=1, max_length=300)
_REASON_FIELD = Field(min_length=1, max_length=300)


class _StrictApiModel(BaseModel):
    """Closed, immutable, coercion-free API model (mirrors U7 strict contracts)."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


# ── request DTOs ────────────────────────────────────────────────────────────


class CreateApprovalRequestApiRequest(_StrictApiModel):
    """Operator request to persist one non-authoritative approval request.

    ``owner_id`` and ``requested_by`` are supplied by the trusted operator
    context in the router, never by this body.
    """

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    request_id: str = _ID_FIELD
    subject: SubjectReference
    capability: str = _CAPABILITY_FIELD
    scope: AuthorityScope
    purpose: str = _PURPOSE_FIELD
    policy_version: str = _POLICY_FIELD
    requested_at: datetime
    valid_from: datetime
    expires_at: datetime
    idempotency_key: str = _IDEMPOTENCY_FIELD


class RecordApprovalDecisionApiRequest(_StrictApiModel):
    """Operator request to append one terminal approval decision.

    ``owner_id`` and ``decided_by`` come from trusted context, never the body.
    Subject, capability, scope, purpose, policy_version and validity come from
    stored request truth, never the body.
    """

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    decision_id: str = _ID_FIELD
    outcome: ApprovalDecisionOutcome
    decided_at: datetime
    reason: str = _REASON_FIELD
    policy_version: str = _POLICY_FIELD
    idempotency_key: str = _IDEMPOTENCY_FIELD


class IssueCapabilityGrantApiRequest(_StrictApiModel):
    """Operator request to issue one grant from an approved decision.

    Subject/capability/scope/purpose come from stored approval truth, never the
    body. ``owner_id`` and ``issued_by`` come from trusted context.
    """

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    grant_id: str = _ID_FIELD
    decision_id: str = _ID_FIELD
    issued_at: datetime
    policy_version: str = _POLICY_FIELD
    idempotency_key: str = _IDEMPOTENCY_FIELD


class RevokeCapabilityGrantApiRequest(_StrictApiModel):
    """Operator request to append one revocation for an existing grant."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    revocation_id: str = _ID_FIELD
    effective_at: datetime
    recorded_at: datetime
    reason: str = _REASON_FIELD
    policy_version: str = _POLICY_FIELD
    idempotency_key: str = _IDEMPOTENCY_FIELD


class EvaluateAuthorityApiRequest(_StrictApiModel):
    """Operator request to evaluate and persist one grant-backed evaluation.

    Subject, capability, scope, purpose come from stored grant truth (the grant
    is identified by ``grant_id``); the body supplies only the evaluation
    identity, time, delegation flag, policy version, and idempotency key.
    """

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    evaluation_id: str = _ID_FIELD
    grant_id: str = _ID_FIELD
    evaluation_time: datetime
    delegation_requested: bool = False
    policy_version: str = _POLICY_FIELD
    idempotency_key: str = _IDEMPOTENCY_FIELD


# ── response DTOs (strict deterministic projections of stored truth) ────────


class ApprovalRequestResponse(_StrictApiModel):
    """Projection of one stored approval request; explicitly non-authoritative."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    request: ApprovalRequest
    authoritative: Literal[False] = False
    note: Literal["An approval request is non-authoritative evidence; it grants nothing."] = (
        "An approval request is non-authoritative evidence; it grants nothing."
    )


class ApprovalDecisionResponse(_StrictApiModel):
    """Projection of one stored terminal decision; not itself a grant."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    decision: ApprovalDecision
    creates_grant: Literal[False] = False
    note: Literal[
        "An approval decision is durable evidence; it does not itself create a grant."
    ] = "An approval decision is durable evidence; it does not itself create a grant."


class CapabilityGrantResponse(_StrictApiModel):
    """Projection of one stored grant; possession is not execution authority."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    grant: CapabilityGrant
    revocation_count: int = Field(ge=0)
    latest_evaluation: AuthorityEvaluationDecision | None = None
    execution_authority: Literal[False] = False
    note: Literal["A grant is evidence only; it is not runtime execution authority."] = (
        "A grant is evidence only; it is not runtime execution authority."
    )


class RevocationResponse(_StrictApiModel):
    """Projection of one stored revocation record."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    revocation: RevocationRecord


class AuthorityEvaluationResponse(_StrictApiModel):
    """Projection of one persisted evaluation; evidence only, not enforcement."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    evaluation: AuthorityEvaluationDecision
    enforced: Literal[False] = False
    note: Literal["An allowed evaluation is evidence only; it is not runtime enforcement."] = (
        "An allowed evaluation is evidence only; it is not runtime enforcement."
    )


class AuthorityChainResponse(_StrictApiModel):
    """Projection of all stored evidence for one owner-scoped request."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    owner_id: str
    approval_request: ApprovalRequest
    approval_decisions: tuple[ApprovalDecision, ...]
    capability_grants: tuple[CapabilityGrant, ...]
    revocations: tuple[RevocationRecord, ...]
    evaluations: tuple[AuthorityEvaluationDecision, ...]


class BoundedApprovalRequestListResponse(_StrictApiModel):
    """Bounded owner-scoped approval-request list."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    owner_id: str
    items: tuple[ApprovalRequest, ...]
    page_size: int = Field(ge=0, le=200)
    truncated: bool


class BoundedCapabilityGrantListResponse(_StrictApiModel):
    """Bounded owner-scoped capability-grant list."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    owner_id: str
    items: tuple[CapabilityGrant, ...]
    page_size: int = Field(ge=0, le=200)
    truncated: bool


class RevocationListResponse(_StrictApiModel):
    """Bounded revocations for one exact owner-scoped grant."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    owner_id: str
    grant_id: str
    items: tuple[RevocationRecord, ...]
    page_size: int = Field(ge=0, le=200)
    truncated: bool


class EvaluationListResponse(_StrictApiModel):
    """Bounded persisted evaluations for one exact owner-scoped grant."""

    schema_version: Literal["authority-api-v1"] = AUTHORITY_API_SCHEMA_VERSION
    owner_id: str
    grant_id: str
    items: tuple[AuthorityEvaluationDecision, ...]
    page_size: int = Field(ge=0, le=200)
    truncated: bool
