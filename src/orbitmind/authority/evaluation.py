"""Deterministic, side-effect-free authority evaluation (U7.0).

``evaluate_authority`` is a total, pure function: same input, same decision;
no clock, no I/O, no mutation, no exception on a well-typed chain. Every
failure mode maps to a stable reason code and the first failing check in the
documented precedence wins. Uncertainty is impossible by construction — any
inconsistency the checks cannot positively classify is a malformed chain, and
malformed fails closed.

The function returns a decision **only**. It never returns a tool, callable,
token, credential, command, import path, or execution handle, and an
``authorized`` decision confers nothing by itself.
"""

from __future__ import annotations

from typing import Final

from orbitmind.authority.contracts import (
    _EVALUATION_DETAILS,
    ApprovalDecisionOutcome,
    AuthorityEvaluationDecision,
    AuthorityEvaluationRequest,
    AuthorityReasonCode,
    OperatorReference,
    SubjectType,
)

# Documented, frozen check precedence. Evaluation walks this order and stops
# at the first failure; tests pin both the order and the first-failure-wins
# semantics.
EVALUATION_PRECEDENCE: Final[tuple[AuthorityReasonCode, ...]] = (
    AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN,
    AuthorityReasonCode.DELEGATION_PROHIBITED,
    AuthorityReasonCode.APPROVAL_NOT_APPROVED,
    AuthorityReasonCode.APPROVAL_GRANT_MISMATCH,
    AuthorityReasonCode.SUBJECT_MISMATCH,
    AuthorityReasonCode.CAPABILITY_MISMATCH,
    AuthorityReasonCode.SCOPE_MISMATCH,
    AuthorityReasonCode.PURPOSE_MISMATCH,
    AuthorityReasonCode.POLICY_VERSION_MISMATCH,
    AuthorityReasonCode.NOT_YET_VALID,
    AuthorityReasonCode.EXPIRED,
    AuthorityReasonCode.REVOKED,
    AuthorityReasonCode.AUTHORIZED,
)


def _chain_is_malformed(request: AuthorityEvaluationRequest) -> bool:
    """True when the supplied chain records do not link to one another exactly."""
    approval = request.approval_request
    decision = request.approval_decision
    grant = request.grant

    if decision.request_id != approval.request_id:
        return True
    if grant.request_id != approval.request_id or grant.decision_id != decision.decision_id:
        return True
    owners = {request.owner_id, approval.owner_id, decision.owner_id, grant.owner_id}
    if len(owners) != 1:
        return True
    # model_copy(update=...) deliberately bypasses Pydantic validation. Treat
    # actor values defensively as opaque objects so a tampered in-memory chain
    # cannot evade the contract's operator-only fields.
    decision_actor: object = decision.decided_by
    issuance_actor: object = grant.issued_by
    if (
        not isinstance(decision_actor, OperatorReference)
        or getattr(decision_actor, "subject_type", None) is not SubjectType.OPERATOR
        or not isinstance(issuance_actor, OperatorReference)
        or getattr(issuance_actor, "subject_type", None) is not SubjectType.OPERATOR
    ):
        return True
    if (
        not approval.requested_at
        <= decision.decided_at
        <= grant.issued_at
        <= request.evaluation_time
    ):
        return True
    for revocation in request.revocations:
        if revocation.grant_id != grant.grant_id or revocation.owner_id != grant.owner_id:
            return True
    # The decision must echo the request it decided, exactly.
    return (
        decision.subject != approval.subject
        or decision.capability != approval.capability
        or decision.scope != approval.scope
        or decision.purpose != approval.purpose
        or decision.policy_version != approval.policy_version
        or decision.validity != approval.validity
    )


def _grant_matches_decision(request: AuthorityEvaluationRequest) -> bool:
    decision = request.approval_decision
    grant = request.grant
    return (
        grant.subject == decision.subject
        and grant.capability == decision.capability
        and grant.scope == decision.scope
        and grant.purpose == decision.purpose
        and grant.policy_version == decision.policy_version
        and grant.validity == decision.validity
    )


def _decide(
    request: AuthorityEvaluationRequest,
    reason_code: AuthorityReasonCode,
    *,
    include_grant: bool,
) -> AuthorityEvaluationDecision:
    return AuthorityEvaluationDecision(
        evaluation_id=request.evaluation_id,
        evaluation_time=request.evaluation_time,
        authorized=reason_code is AuthorityReasonCode.AUTHORIZED,
        reason_code=reason_code,
        grant_id=request.grant.grant_id if include_grant else None,
        detail=_EVALUATION_DETAILS[reason_code],
    )


def evaluate_authority(request: AuthorityEvaluationRequest) -> AuthorityEvaluationDecision:
    """Evaluate one exact authority question against its complete chain.

    Deterministic, side-effect free, fail-closed. Returns a decision only.
    """
    if _chain_is_malformed(request):
        return _decide(request, AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN, include_grant=False)
    if request.delegation_requested:
        return _decide(request, AuthorityReasonCode.DELEGATION_PROHIBITED, include_grant=True)
    if request.approval_decision.outcome is not ApprovalDecisionOutcome.APPROVED:
        return _decide(request, AuthorityReasonCode.APPROVAL_NOT_APPROVED, include_grant=True)
    if not _grant_matches_decision(request):
        return _decide(request, AuthorityReasonCode.APPROVAL_GRANT_MISMATCH, include_grant=True)

    grant = request.grant
    if request.subject != grant.subject:
        return _decide(request, AuthorityReasonCode.SUBJECT_MISMATCH, include_grant=True)
    if request.capability != grant.capability:
        return _decide(request, AuthorityReasonCode.CAPABILITY_MISMATCH, include_grant=True)
    if request.scope != grant.scope:
        return _decide(request, AuthorityReasonCode.SCOPE_MISMATCH, include_grant=True)
    if request.purpose != grant.purpose:
        return _decide(request, AuthorityReasonCode.PURPOSE_MISMATCH, include_grant=True)
    if request.policy_version != grant.policy_version:
        return _decide(request, AuthorityReasonCode.POLICY_VERSION_MISMATCH, include_grant=True)

    if request.evaluation_time < grant.validity.valid_from:
        return _decide(request, AuthorityReasonCode.NOT_YET_VALID, include_grant=True)
    if request.evaluation_time >= grant.validity.expires_at:
        return _decide(request, AuthorityReasonCode.EXPIRED, include_grant=True)

    # Revocations are normalized to earliest-first; the earliest effective
    # revocation governs: evaluation_time >= effective_at means revoked.
    for revocation in request.revocations:
        if request.evaluation_time >= revocation.effective_at:
            return _decide(request, AuthorityReasonCode.REVOKED, include_grant=True)

    return _decide(request, AuthorityReasonCode.AUTHORIZED, include_grant=True)
