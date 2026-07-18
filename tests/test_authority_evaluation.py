"""Deterministic evaluation tests: precedence, boundaries, fail-closed codes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityEvaluationRequest,
    AuthorityReasonCode,
    AuthorityScope,
    CapabilityGrant,
    OperatorReference,
    RevocationRecord,
    ScopeConstraint,
    SubjectReference,
    SubjectType,
    ValidityWindow,
    canonical_authority_json,
)
from orbitmind.authority.evaluation import EVALUATION_PRECEDENCE, evaluate_authority

T0 = datetime(2026, 7, 18, 0, 0, tzinfo=UTC)
EXPIRY = T0 + timedelta(days=30)
IST = timezone(timedelta(hours=5, minutes=30))

_SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
_OTHER_SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0002")
_OPERATOR = OperatorReference(subject_id="operator-piyush-1")
_SCOPE = AuthorityScope(
    resource_type="repository",
    resource_id="orbitmind-main",
    constraints=(ScopeConstraint(name="ref", value="rev-abc123"),),
)
_OTHER_SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-docs")
_PURPOSE = "Read one pinned revision for review evidence."
_POLICY = "authority-policy-v1"
_WINDOW = ValidityWindow(valid_from=T0, expires_at=EXPIRY)


def _chain(**overrides: Any) -> AuthorityEvaluationRequest:
    request = ApprovalRequest(
        request_id="req-00000001",
        owner_id="owner-piyush-01",
        requested_by="owner-piyush-01",
        subject=_SUBJECT,
        capability="repository_read",
        scope=_SCOPE,
        purpose=_PURPOSE,
        policy_version=_POLICY,
        requested_at=T0 - timedelta(hours=1),
        validity=_WINDOW,
    )
    decision = ApprovalDecision(
        decision_id="dec-00000001",
        request_id=request.request_id,
        owner_id=request.owner_id,
        decided_by=_OPERATOR,
        outcome=ApprovalDecisionOutcome.APPROVED,
        decided_at=T0 - timedelta(minutes=30),
        reason="Approved for one bounded review.",
        subject=request.subject,
        capability=request.capability,
        scope=request.scope,
        purpose=request.purpose,
        policy_version=request.policy_version,
        validity=request.validity,
    )
    grant = CapabilityGrant(
        grant_id="grant-00000001",
        owner_id=request.owner_id,
        request_id=request.request_id,
        decision_id=decision.decision_id,
        issued_by=_OPERATOR,
        issued_at=T0 - timedelta(minutes=15),
        subject=request.subject,
        capability=request.capability,
        scope=request.scope,
        purpose=request.purpose,
        policy_version=request.policy_version,
        validity=request.validity,
    )
    values: dict[str, Any] = {
        "evaluation_id": "eval-0000001",
        "owner_id": request.owner_id,
        "evaluation_time": T0 + timedelta(days=1),
        "subject": request.subject,
        "capability": request.capability,
        "scope": request.scope,
        "purpose": request.purpose,
        "policy_version": request.policy_version,
        "approval_request": request,
        "approval_decision": decision,
        "grant": grant,
        "revocations": (),
    }
    values.update(overrides)
    return AuthorityEvaluationRequest(**values)


def _revocation(effective_at: datetime, rid: str = "rvk-00000001") -> RevocationRecord:
    return RevocationRecord(
        revocation_id=rid,
        grant_id="grant-00000001",
        owner_id="owner-piyush-01",
        revoked_by="owner-piyush-01",
        effective_at=effective_at,
        recorded_at=effective_at,
        reason="Revocation for evaluation tests.",
    )


# --- authorized path and determinism -----------------------------------------


def test_exact_chain_is_authorized_and_references_the_grant() -> None:
    decision = evaluate_authority(_chain())
    assert decision.authorized is True
    assert decision.reason_code is AuthorityReasonCode.AUTHORIZED
    assert decision.grant_id == "grant-00000001"
    assert decision.evaluation_id == "eval-0000001"


def test_evaluation_is_deterministic_and_side_effect_free() -> None:
    request = _chain()
    first = evaluate_authority(request)
    second = evaluate_authority(request)
    assert first == second
    assert canonical_authority_json(first) == canonical_authority_json(second)
    # Input chain is unchanged (frozen models; equality re-checked defensively).
    assert request == _chain()


def test_authorized_result_is_a_decision_not_a_credential() -> None:
    decision = evaluate_authority(_chain())
    payload = decision.model_dump()
    assert set(payload) == {
        "schema_version",
        "evaluation_id",
        "evaluation_time",
        "authorized",
        "reason_code",
        "grant_id",
        "detail",
    }
    for name in payload:
        for fragment in ("secret", "token", "credential", "command", "handle", "callable"):
            assert fragment not in name


# --- fail-closed reason codes --------------------------------------------------


def test_rejected_approval_cannot_generate_authority() -> None:
    chain = _chain()
    rejected = chain.approval_decision.model_copy(
        update={"outcome": ApprovalDecisionOutcome.REJECTED}
    )
    decision = evaluate_authority(chain.model_copy(update={"approval_decision": rejected}))
    assert decision.authorized is False
    assert decision.reason_code is AuthorityReasonCode.APPROVAL_NOT_APPROVED


def test_grant_decision_mismatch_fails_closed() -> None:
    chain = _chain()
    drifted = chain.grant.model_copy(update={"purpose": "A different purpose entirely."})
    decision = evaluate_authority(chain.model_copy(update={"grant": drifted}))
    assert decision.reason_code is AuthorityReasonCode.APPROVAL_GRANT_MISMATCH


def test_subject_capability_scope_purpose_policy_mismatches() -> None:
    assert (
        evaluate_authority(_chain(subject=_OTHER_SUBJECT)).reason_code
        is AuthorityReasonCode.SUBJECT_MISMATCH
    )
    assert (
        evaluate_authority(_chain(capability="repository_write")).reason_code
        is AuthorityReasonCode.CAPABILITY_MISMATCH
    )
    assert (
        evaluate_authority(_chain(scope=_OTHER_SCOPE)).reason_code
        is AuthorityReasonCode.SCOPE_MISMATCH
    )
    assert (
        evaluate_authority(_chain(purpose="A different purpose entirely.")).reason_code
        is AuthorityReasonCode.PURPOSE_MISMATCH
    )
    assert (
        evaluate_authority(_chain(policy_version="authority-policy-v2")).reason_code
        is AuthorityReasonCode.POLICY_VERSION_MISMATCH
    )


def test_scope_constraint_difference_is_a_scope_mismatch() -> None:
    narrowed = AuthorityScope(
        resource_type="repository",
        resource_id="orbitmind-main",
        constraints=(ScopeConstraint(name="ref", value="rev-def456"),),
    )
    assert (
        evaluate_authority(_chain(scope=narrowed)).reason_code is AuthorityReasonCode.SCOPE_MISMATCH
    )


def test_delegation_is_prohibited_in_v1() -> None:
    decision = evaluate_authority(_chain(delegation_requested=True))
    assert decision.authorized is False
    assert decision.reason_code is AuthorityReasonCode.DELEGATION_PROHIBITED


def test_non_operator_approval_or_issuance_actor_is_malformed() -> None:
    chain = _chain()
    agent_actor = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
    decision = chain.approval_decision.model_copy(update={"decided_by": agent_actor})
    assert (
        evaluate_authority(chain.model_copy(update={"approval_decision": decision})).reason_code
        is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    )
    grant = chain.grant.model_copy(update={"issued_by": agent_actor})
    assert (
        evaluate_authority(chain.model_copy(update={"grant": grant})).reason_code
        is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    )
    spoofed_operator = _OPERATOR.model_copy(update={"subject_type": SubjectType.AGENT})
    spoofed_decision = chain.approval_decision.model_copy(update={"decided_by": spoofed_operator})
    assert (
        evaluate_authority(
            chain.model_copy(update={"approval_decision": spoofed_decision})
        ).reason_code
        is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    )


# --- temporal boundaries ---------------------------------------------------------


def test_validity_boundaries_are_exact_half_open() -> None:
    at_valid_from = evaluate_authority(_chain(evaluation_time=T0))
    assert at_valid_from.reason_code is AuthorityReasonCode.AUTHORIZED
    just_before = evaluate_authority(_chain(evaluation_time=T0 - timedelta(microseconds=1)))
    assert just_before.reason_code is AuthorityReasonCode.NOT_YET_VALID
    just_before_expiry = evaluate_authority(
        _chain(evaluation_time=EXPIRY - timedelta(microseconds=1))
    )
    assert just_before_expiry.reason_code is AuthorityReasonCode.AUTHORIZED
    at_expiry = evaluate_authority(_chain(evaluation_time=EXPIRY))
    assert at_expiry.reason_code is AuthorityReasonCode.EXPIRED


def test_timezone_expression_does_not_change_the_decision() -> None:
    utc_decision = evaluate_authority(_chain(evaluation_time=T0))
    ist_decision = evaluate_authority(_chain(evaluation_time=T0.astimezone(IST)))
    assert utc_decision == ist_decision
    # A different instant expressed in IST behaves by instant, not by wall clock.
    before = evaluate_authority(_chain(evaluation_time=(T0 - timedelta(seconds=1)).astimezone(IST)))
    assert before.reason_code is AuthorityReasonCode.NOT_YET_VALID


def test_request_decision_issuance_and_evaluation_are_causally_ordered() -> None:
    chain = _chain()
    decision_before_request = chain.approval_decision.model_copy(
        update={"decided_at": chain.approval_request.requested_at - timedelta(microseconds=1)}
    )
    assert (
        evaluate_authority(
            chain.model_copy(update={"approval_decision": decision_before_request})
        ).reason_code
        is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    )
    grant_before_decision = chain.grant.model_copy(
        update={"issued_at": chain.approval_decision.decided_at - timedelta(microseconds=1)}
    )
    assert (
        evaluate_authority(chain.model_copy(update={"grant": grant_before_decision})).reason_code
        is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    )
    future_grant = chain.grant.model_copy(
        update={"issued_at": chain.evaluation_time + timedelta(microseconds=1)}
    )
    assert (
        evaluate_authority(chain.model_copy(update={"grant": future_grant})).reason_code
        is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    )


def test_revocation_boundary_semantics() -> None:
    effective = T0 + timedelta(hours=12)
    revoked_chain_kwargs = {"revocations": (_revocation(effective),)}
    before = evaluate_authority(
        _chain(evaluation_time=effective - timedelta(seconds=1), **revoked_chain_kwargs)
    )
    assert before.reason_code is AuthorityReasonCode.AUTHORIZED
    at_effective = evaluate_authority(_chain(evaluation_time=effective, **revoked_chain_kwargs))
    assert at_effective.reason_code is AuthorityReasonCode.REVOKED
    after = evaluate_authority(
        _chain(evaluation_time=effective + timedelta(days=1), **revoked_chain_kwargs)
    )
    assert after.reason_code is AuthorityReasonCode.REVOKED


def test_earliest_valid_revocation_governs() -> None:
    early = _revocation(T0 + timedelta(hours=6), rid="rvk-00000001")
    late = _revocation(T0 + timedelta(days=20), rid="rvk-00000002")
    decision = evaluate_authority(
        _chain(evaluation_time=T0 + timedelta(hours=6), revocations=(late, early))
    )
    assert decision.reason_code is AuthorityReasonCode.REVOKED
    not_yet_effective = evaluate_authority(
        _chain(evaluation_time=T0 + timedelta(hours=5), revocations=(late, early))
    )
    assert not_yet_effective.reason_code is AuthorityReasonCode.AUTHORIZED


# --- malformed chains --------------------------------------------------------------


def test_broken_linkage_is_malformed_and_fails_closed() -> None:
    chain = _chain()
    wrong_request_link = chain.approval_decision.model_copy(update={"request_id": "req-00000099"})
    decision = evaluate_authority(
        chain.model_copy(update={"approval_decision": wrong_request_link})
    )
    assert decision.reason_code is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    assert decision.authorized is False
    assert decision.grant_id is None


def test_owner_mismatch_is_malformed() -> None:
    chain = _chain()
    foreign_grant = chain.grant.model_copy(update={"owner_id": "owner-someone-9"})
    decision = evaluate_authority(chain.model_copy(update={"grant": foreign_grant}))
    assert decision.reason_code is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN


def test_revocation_for_another_grant_is_malformed() -> None:
    stray = RevocationRecord(
        revocation_id="rvk-00000009",
        grant_id="grant-00000099",
        owner_id="owner-piyush-01",
        revoked_by="owner-piyush-01",
        effective_at=T0,
        recorded_at=T0,
        reason="Points at a different grant.",
    )
    decision = evaluate_authority(_chain(revocations=(stray,)))
    assert decision.reason_code is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN


def test_decision_request_echo_drift_is_malformed() -> None:
    chain = _chain()
    drifted = chain.approval_decision.model_copy(update={"capability": "repository_write"})
    decision = evaluate_authority(chain.model_copy(update={"approval_decision": drifted}))
    assert decision.reason_code is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN


# --- precedence -----------------------------------------------------------------


def test_precedence_is_documented_and_first_failure_wins() -> None:
    assert EVALUATION_PRECEDENCE[0] is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN
    assert EVALUATION_PRECEDENCE[-1] is AuthorityReasonCode.AUTHORIZED
    assert len(EVALUATION_PRECEDENCE) == len(set(EVALUATION_PRECEDENCE)) == 13
    # A chain that is simultaneously rejected AND expired reports the earlier
    # check in the precedence (approval_not_approved).
    chain = _chain(evaluation_time=EXPIRY + timedelta(days=1))
    rejected = chain.approval_decision.model_copy(
        update={"outcome": ApprovalDecisionOutcome.REJECTED}
    )
    decision = evaluate_authority(chain.model_copy(update={"approval_decision": rejected}))
    assert decision.reason_code is AuthorityReasonCode.APPROVAL_NOT_APPROVED
    # Malformed beats everything, including delegation.
    broken = chain.approval_decision.model_copy(update={"request_id": "req-00000099"})
    decision = evaluate_authority(
        chain.model_copy(update={"approval_decision": broken, "delegation_requested": True})
    )
    assert decision.reason_code is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN


def test_every_denial_reason_is_reachable_and_stable() -> None:
    observed: set[AuthorityReasonCode] = set()
    observed.add(evaluate_authority(_chain()).reason_code)
    observed.add(evaluate_authority(_chain(delegation_requested=True)).reason_code)
    chain = _chain()
    observed.add(
        evaluate_authority(
            chain.model_copy(
                update={
                    "approval_decision": chain.approval_decision.model_copy(
                        update={"outcome": ApprovalDecisionOutcome.REJECTED}
                    )
                }
            )
        ).reason_code
    )
    observed.add(
        evaluate_authority(
            chain.model_copy(
                update={
                    "grant": chain.grant.model_copy(
                        update={"purpose": "A different purpose entirely."}
                    )
                }
            )
        ).reason_code
    )
    observed.add(evaluate_authority(_chain(subject=_OTHER_SUBJECT)).reason_code)
    observed.add(evaluate_authority(_chain(capability="repository_write")).reason_code)
    observed.add(evaluate_authority(_chain(scope=_OTHER_SCOPE)).reason_code)
    observed.add(evaluate_authority(_chain(purpose="A different purpose entirely.")).reason_code)
    observed.add(evaluate_authority(_chain(policy_version="authority-policy-v2")).reason_code)
    observed.add(
        evaluate_authority(_chain(evaluation_time=T0 - timedelta(microseconds=1))).reason_code
    )
    observed.add(evaluate_authority(_chain(evaluation_time=EXPIRY)).reason_code)
    observed.add(
        evaluate_authority(
            _chain(evaluation_time=T0 + timedelta(days=2), revocations=(_revocation(T0),))
        ).reason_code
    )
    observed.add(
        evaluate_authority(
            chain.model_copy(
                update={
                    "approval_decision": chain.approval_decision.model_copy(
                        update={"request_id": "req-00000099"}
                    )
                }
            )
        ).reason_code
    )
    assert observed == set(AuthorityReasonCode)
