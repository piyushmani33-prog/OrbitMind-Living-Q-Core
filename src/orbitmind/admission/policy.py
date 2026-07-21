"""Deterministic, side-effect-free Operation Admission v0 policy (U7.4).

``evaluate_admission`` is a total, pure function: same input, same decision; no
clock, no I/O, no mutation, no execution. Every failure mode maps to a stable
public-safe reason code and the first failing check in the documented precedence
wins. It returns a decision only — never a tool, callable, token, credential,
command, or execution handle, and an ``admitted`` decision confers nothing.

Key invariants pinned by the ordering:
- forbidden operation kinds are denied **before** any authority is consulted;
- the mandatory human-approval gate is evaluated **after** authority, so a valid
  grant can never bypass required approval;
- owner/actor claims are checked against the trusted context, never trusted from
  the proposal;
- authority time-dependence flows through ``context.evaluated_at`` only (the
  orchestration bridge builds the :class:`AuthorityFinding` at that instant).
"""

from __future__ import annotations

from typing import Final

from orbitmind.admission.contracts import (
    OPERATION_PROFILES as _OPERATION_PROFILES,
)
from orbitmind.admission.contracts import (
    AdmissionDecision,
    AdmissionEvaluationContext,
    AdmissionOperationKind,
    AdmissionReasonCode,
    AuthorityFinding,
    OperationProfile,
    OperationProposal,
    detail_for_reason,
    outcome_for_reason,
)

# Documented, frozen check precedence (first-failure-wins). Tests pin this order.
ADMISSION_PRECEDENCE: Final[tuple[AdmissionReasonCode, ...]] = (
    AdmissionReasonCode.OWNER_MISMATCH,
    AdmissionReasonCode.ACTOR_MISMATCH,
    AdmissionReasonCode.UNSUPPORTED_OPERATION_KIND,
    AdmissionReasonCode.OPERATION_PROFILE_MISMATCH,
    AdmissionReasonCode.FORBIDDEN_OPERATION_KIND,
    AdmissionReasonCode.AUTHORITY_REQUIRED,
    AdmissionReasonCode.AUTHORITY_NOT_FOUND,
    AdmissionReasonCode.AUTHORITY_ACTOR_MISMATCH,
    AdmissionReasonCode.CAPABILITY_MISMATCH,
    AdmissionReasonCode.SCOPE_MISMATCH,
    AdmissionReasonCode.AUTHORITY_NOT_YET_VALID,
    AdmissionReasonCode.AUTHORITY_EXPIRED,
    AdmissionReasonCode.AUTHORITY_REVOKED,
    AdmissionReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED,
    AdmissionReasonCode.ADMITTED_BY_POLICY,
)

# Authority-failure reason codes the policy may surface from an AuthorityFinding.
_AUTHORITY_FAILURE_REASONS: Final[frozenset[AdmissionReasonCode]] = frozenset(
    {
        AdmissionReasonCode.AUTHORITY_ACTOR_MISMATCH,
        AdmissionReasonCode.CAPABILITY_MISMATCH,
        AdmissionReasonCode.SCOPE_MISMATCH,
        AdmissionReasonCode.AUTHORITY_NOT_YET_VALID,
        AdmissionReasonCode.AUTHORITY_EXPIRED,
        AdmissionReasonCode.AUTHORITY_REVOKED,
    }
)


def resolve_operation_kind(token: str) -> AdmissionOperationKind | None:
    """Resolve a bounded operation-kind token to a known kind, or ``None``."""
    try:
        return AdmissionOperationKind(token)
    except ValueError:
        return None


def operation_profile(kind: AdmissionOperationKind) -> OperationProfile:
    """The authoritative immutable profile for a known operation kind."""
    return _OPERATION_PROFILES[kind]


def _decision(
    context: AdmissionEvaluationContext,
    reason: AdmissionReasonCode,
    *,
    resolved_grant_id: str | None = None,
) -> AdmissionDecision:
    return AdmissionDecision(
        outcome=outcome_for_reason(reason),
        primary_reason_code=reason,
        reason_codes=(reason,),
        policy_version=context.policy_version,
        evaluated_at=context.evaluated_at,
        resolved_grant_id=resolved_grant_id,
        detail=detail_for_reason(reason),
    )


def evaluate_admission(
    proposal: OperationProposal,
    context: AdmissionEvaluationContext,
    authority_finding: AuthorityFinding,
) -> AdmissionDecision:
    """Evaluate one operation proposal deterministically and fail-closed.

    Returns a decision only; performs no execution and reads no clock.
    """
    # 1-2: owner/actor claims must match the trusted context.
    if proposal.owner_id != context.authoritative_owner_id:
        return _decision(context, AdmissionReasonCode.OWNER_MISMATCH)
    if proposal.actor_id != context.authoritative_actor_id:
        return _decision(context, AdmissionReasonCode.ACTOR_MISMATCH)

    # 3: resolve the operation-kind token.
    kind = resolve_operation_kind(proposal.operation_kind)
    if kind is None:
        return _decision(context, AdmissionReasonCode.UNSUPPORTED_OPERATION_KIND)
    profile = operation_profile(kind)

    # 4: proposal echoes must agree exactly with the authoritative profile. This is
    # checked BEFORE the forbidden gate so a caller can never disguise an operation
    # by echoing a weaker profile (a mismatched echo is denied as a profile
    # mismatch, never silently treated as a different kind).
    if (
        proposal.requested_capability != profile.required_capability
        or proposal.side_effect_class is not profile.side_effect_class
        or proposal.risk_class is not profile.risk_class
    ):
        return _decision(context, AdmissionReasonCode.OPERATION_PROFILE_MISMATCH)

    # 5: forbidden kinds are denied once the profile agrees, still before any
    # authority is consulted.
    if profile.forbidden_in_v0:
        return _decision(context, AdmissionReasonCode.FORBIDDEN_OPERATION_KIND)

    # 6: authority evidence, when the profile requires it.
    resolved_grant_id = authority_finding.resolved_grant_id
    if profile.authority_required:
        if not authority_finding.referenced:
            return _decision(context, AdmissionReasonCode.AUTHORITY_REQUIRED)
        if not authority_finding.resolved:
            return _decision(context, AdmissionReasonCode.AUTHORITY_NOT_FOUND)
        if not authority_finding.authorized:
            reason = authority_finding.reason
            if reason not in _AUTHORITY_FAILURE_REASONS:
                # Fail closed: an unresolved/unexpected authority state is not admissible.
                reason = AdmissionReasonCode.AUTHORITY_NOT_FOUND
            return _decision(context, reason, resolved_grant_id=resolved_grant_id)

    # 7: mandatory human approval is evaluated AFTER authority.
    if profile.approval_required:
        return _decision(
            context,
            AdmissionReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED,
            resolved_grant_id=resolved_grant_id,
        )

    # 8: admissible by policy.
    return _decision(
        context, AdmissionReasonCode.ADMITTED_BY_POLICY, resolved_grant_id=resolved_grant_id
    )
