"""Deterministic decision-matrix coverage for the pure Operation Admission policy."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from orbitmind.admission.contracts import (
    OPERATION_PROFILES,
    AdmissionEvaluationContext,
    AdmissionOperationKind,
    AdmissionOutcome,
    AdmissionReasonCode,
    AdmissionRiskClass,
    AdmissionSideEffectClass,
    AuthorityFinding,
    OperationProposal,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.admission.policy import evaluate_admission

T0 = datetime(2026, 7, 21, tzinfo=UTC)
OWNER = "owner-piyush-01"
ACTOR = "agent-dev-0001"
GRANT = "grant-00000001"
SCOPE = ProposalScope(resource_type="repository", resource_id="orbitmind-main")

CONTEXT = AdmissionEvaluationContext(
    authoritative_owner_id=OWNER,
    authoritative_actor_id=ACTOR,
    evaluated_at=T0,
    policy_version="operation-admission-v0",
)

_EMPTY_FINDING = AuthorityFinding(
    required=False, referenced=False, resolved=False, authorized=False
)


def _proposal(kind: AdmissionOperationKind, **overrides: Any) -> OperationProposal:
    profile = OPERATION_PROFILES[kind]
    values: dict[str, Any] = {
        "proposal_id": "prop-00000001",
        "owner_id": OWNER,
        "actor_id": ACTOR,
        "actor_type": ProposalActorType.AGENT,
        "operation_kind": kind.value,
        "requested_capability": profile.required_capability,
        "requested_scope": SCOPE,
        "side_effect_class": profile.side_effect_class,
        "risk_class": profile.risk_class,
        "purpose": "Bounded operation for review evidence.",
        "requested_at": T0,
        "idempotency_key": "adm-key-0001",
    }
    values.update(overrides)
    return OperationProposal(**values)


def _authorized() -> AuthorityFinding:
    return AuthorityFinding(
        required=True, referenced=True, resolved=True, authorized=True, resolved_grant_id=GRANT
    )


def _unauthorized(reason: AdmissionReasonCode) -> AuthorityFinding:
    return AuthorityFinding(
        required=True,
        referenced=True,
        resolved=True,
        authorized=False,
        reason=reason,
        resolved_grant_id=GRANT,
    )


@pytest.mark.parametrize(
    "kind",
    [AdmissionOperationKind.READ_REPOSITORY, AdmissionOperationKind.RUN_LOCAL_VALIDATION],
)
def test_no_authority_kinds_are_admitted_by_policy(kind: AdmissionOperationKind) -> None:
    decision = evaluate_admission(_proposal(kind), CONTEXT, _EMPTY_FINDING)
    assert decision.outcome is AdmissionOutcome.ADMITTED
    assert decision.primary_reason_code is AdmissionReasonCode.ADMITTED_BY_POLICY


@pytest.mark.parametrize(
    "kind",
    [AdmissionOperationKind.PROPOSE_FILE_CHANGE, AdmissionOperationKind.CREATE_ISOLATED_WORKTREE],
)
def test_authority_required_admitted_only_with_valid_authority(
    kind: AdmissionOperationKind,
) -> None:
    admitted = evaluate_admission(
        _proposal(kind, requested_authority_grant_id=GRANT), CONTEXT, _authorized()
    )
    assert admitted.outcome is AdmissionOutcome.ADMITTED
    assert admitted.resolved_grant_id == GRANT

    missing = evaluate_admission(
        _proposal(kind),
        CONTEXT,
        AuthorityFinding(required=True, referenced=False, resolved=False, authorized=False),
    )
    assert missing.outcome is AdmissionOutcome.DENIED
    assert missing.primary_reason_code is AdmissionReasonCode.AUTHORITY_REQUIRED


@pytest.mark.parametrize(
    "kind",
    [
        AdmissionOperationKind.INSTALL_DEPENDENCY,
        AdmissionOperationKind.ACCESS_SECRET,
        AdmissionOperationKind.CALL_EXTERNAL_PROVIDER,
        AdmissionOperationKind.PUSH_BRANCH,
        AdmissionOperationKind.CREATE_PULL_REQUEST,
        AdmissionOperationKind.CLOUD_QUANTUM_EXECUTION,
    ],
)
def test_mandatory_approval_kinds_require_authority_then_stay_approval_required(
    kind: AdmissionOperationKind,
) -> None:
    # Valid authority does NOT admit — the outcome remains approval_required.
    valid = evaluate_admission(
        _proposal(kind, requested_authority_grant_id=GRANT), CONTEXT, _authorized()
    )
    assert valid.outcome is AdmissionOutcome.APPROVAL_REQUIRED
    assert valid.primary_reason_code is AdmissionReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED
    assert valid.resolved_grant_id == GRANT

    # Missing/invalid authority denies before the approval gate is reached.
    denied = evaluate_admission(
        _proposal(kind, requested_authority_grant_id=GRANT),
        CONTEXT,
        _unauthorized(AdmissionReasonCode.AUTHORITY_REVOKED),
    )
    assert denied.outcome is AdmissionOutcome.DENIED
    assert denied.primary_reason_code is AdmissionReasonCode.AUTHORITY_REVOKED


@pytest.mark.parametrize(
    "kind",
    [
        AdmissionOperationKind.MERGE_PULL_REQUEST,
        AdmissionOperationKind.DEPLOY,
        AdmissionOperationKind.SPEND_MONEY,
        AdmissionOperationKind.SEND_EXTERNAL_COMMUNICATION,
        AdmissionOperationKind.HARDWARE_CONTROL,
    ],
)
def test_forbidden_kinds_denied_before_authority(kind: AdmissionOperationKind) -> None:
    # Even if a (spurious) authorized finding is supplied, forbidden wins first.
    decision = evaluate_admission(
        _proposal(kind, requested_authority_grant_id=GRANT), CONTEXT, _authorized()
    )
    assert decision.outcome is AdmissionOutcome.DENIED
    assert decision.primary_reason_code is AdmissionReasonCode.FORBIDDEN_OPERATION_KIND
    # Forbidden denial records no resolved grant (authority was never consulted).
    assert decision.resolved_grant_id is None


def test_unknown_operation_kind_is_unsupported() -> None:
    proposal = _proposal(AdmissionOperationKind.READ_REPOSITORY, operation_kind="frobnicate_widget")
    decision = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    assert decision.outcome is AdmissionOutcome.DENIED
    assert decision.primary_reason_code is AdmissionReasonCode.UNSUPPORTED_OPERATION_KIND


def test_owner_and_actor_claims_checked_against_trusted_context() -> None:
    owner_bad = _proposal(AdmissionOperationKind.READ_REPOSITORY, owner_id="owner-someone-99")
    assert (
        evaluate_admission(owner_bad, CONTEXT, _EMPTY_FINDING).primary_reason_code
        is AdmissionReasonCode.OWNER_MISMATCH
    )
    actor_bad = _proposal(AdmissionOperationKind.READ_REPOSITORY, actor_id="agent-dev-0002")
    assert (
        evaluate_admission(actor_bad, CONTEXT, _EMPTY_FINDING).primary_reason_code
        is AdmissionReasonCode.ACTOR_MISMATCH
    )


@pytest.mark.parametrize(
    "override",
    [
        {"requested_capability": "repository_write_proposal"},
        {"side_effect_class": AdmissionSideEffectClass.IRREVERSIBLE_REAL_WORLD},
        {"risk_class": AdmissionRiskClass.CRITICAL},
    ],
)
def test_profile_echo_mismatch_is_denied(override: dict[str, Any]) -> None:
    # read_repository profile: repository_read / local_read / low. Any disagreeing echo denies.
    proposal = _proposal(AdmissionOperationKind.READ_REPOSITORY, **override)
    decision = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    assert decision.outcome is AdmissionOutcome.DENIED
    assert decision.primary_reason_code is AdmissionReasonCode.OPERATION_PROFILE_MISMATCH


def test_authority_required_but_not_referenced() -> None:
    decision = evaluate_admission(
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE),
        CONTEXT,
        AuthorityFinding(required=True, referenced=False, resolved=False, authorized=False),
    )
    assert decision.primary_reason_code is AdmissionReasonCode.AUTHORITY_REQUIRED


def test_authority_not_found_is_denied() -> None:
    decision = evaluate_admission(
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
        CONTEXT,
        AuthorityFinding(required=True, referenced=True, resolved=False, authorized=False),
    )
    assert decision.primary_reason_code is AdmissionReasonCode.AUTHORITY_NOT_FOUND


@pytest.mark.parametrize(
    "reason",
    [
        AdmissionReasonCode.AUTHORITY_ACTOR_MISMATCH,
        AdmissionReasonCode.CAPABILITY_MISMATCH,
        AdmissionReasonCode.SCOPE_MISMATCH,
        AdmissionReasonCode.AUTHORITY_NOT_YET_VALID,
        AdmissionReasonCode.AUTHORITY_EXPIRED,
        AdmissionReasonCode.AUTHORITY_REVOKED,
    ],
)
def test_authority_failure_reasons_are_surfaced(reason: AdmissionReasonCode) -> None:
    decision = evaluate_admission(
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
        CONTEXT,
        _unauthorized(reason),
    )
    assert decision.outcome is AdmissionOutcome.DENIED
    assert decision.primary_reason_code is reason


def test_decision_is_deterministic_and_reason_ordering_holds() -> None:
    proposal = _proposal(AdmissionOperationKind.READ_REPOSITORY)
    first = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    second = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    assert first == second
    assert first.reason_codes[-1] is first.primary_reason_code
    assert first.policy_version == "operation-admission-v0"
    assert first.evaluated_at == T0


# --- precedence correction: profile agreement is checked BEFORE the forbidden gate ---


def test_forbidden_kind_with_mismatched_profile_is_profile_mismatch() -> None:
    # A deploy proposal carrying read_repository capability/side-effect/risk echoes must be
    # denied as operation_profile_mismatch — the profile disagreement wins over forbidden.
    read_profile = OPERATION_PROFILES[AdmissionOperationKind.READ_REPOSITORY]
    proposal = _proposal(
        AdmissionOperationKind.DEPLOY,
        requested_capability=read_profile.required_capability,
        side_effect_class=read_profile.side_effect_class,
        risk_class=read_profile.risk_class,
    )
    decision = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    assert decision.outcome is AdmissionOutcome.DENIED
    assert decision.primary_reason_code is AdmissionReasonCode.OPERATION_PROFILE_MISMATCH


def test_forbidden_kind_with_correct_profile_is_forbidden() -> None:
    # A deploy proposal carrying the authoritative deploy profile is denied as
    # forbidden_operation_kind (only reachable once the profile agrees).
    decision = evaluate_admission(_proposal(AdmissionOperationKind.DEPLOY), CONTEXT, _EMPTY_FINDING)
    assert decision.outcome is AdmissionOutcome.DENIED
    assert decision.primary_reason_code is AdmissionReasonCode.FORBIDDEN_OPERATION_KIND


def test_authority_result_cannot_bypass_or_reorder_profile_or_forbidden() -> None:
    # Supplying an authorized (or any) AuthorityFinding changes neither the
    # profile-mismatch nor the forbidden outcome, and no grant is recorded — authority
    # is never consulted for these earlier checks.
    read_profile = OPERATION_PROFILES[AdmissionOperationKind.READ_REPOSITORY]
    mismatched = _proposal(
        AdmissionOperationKind.DEPLOY,
        requested_capability=read_profile.required_capability,
        side_effect_class=read_profile.side_effect_class,
        risk_class=read_profile.risk_class,
        requested_authority_grant_id=GRANT,
    )
    for finding in (
        _EMPTY_FINDING,
        _authorized(),
        _unauthorized(AdmissionReasonCode.AUTHORITY_REVOKED),
    ):
        d = evaluate_admission(mismatched, CONTEXT, finding)
        assert d.primary_reason_code is AdmissionReasonCode.OPERATION_PROFILE_MISMATCH
        assert d.resolved_grant_id is None

    forbidden = _proposal(AdmissionOperationKind.DEPLOY, requested_authority_grant_id=GRANT)
    for finding in (
        _EMPTY_FINDING,
        _authorized(),
        _unauthorized(AdmissionReasonCode.AUTHORITY_REVOKED),
    ):
        d = evaluate_admission(forbidden, CONTEXT, finding)
        assert d.primary_reason_code is AdmissionReasonCode.FORBIDDEN_OPERATION_KIND
        assert d.resolved_grant_id is None


def test_repeated_evaluation_is_deterministic_including_checksum() -> None:
    from orbitmind.admission.contracts import decision_checksum_source

    proposal = _proposal(AdmissionOperationKind.DEPLOY)

    def _checksum(decision: object) -> str:
        d = decision  # AdmissionDecision
        return decision_checksum_source(
            policy_version=d.policy_version,  # type: ignore[attr-defined]
            proposal_fingerprint="0" * 64,
            outcome=d.outcome,  # type: ignore[attr-defined]
            reason_codes=d.reason_codes,  # type: ignore[attr-defined]
            evaluated_at=d.evaluated_at,  # type: ignore[attr-defined]
            resolved_grant_id=d.resolved_grant_id,  # type: ignore[attr-defined]
        )

    first = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    second = evaluate_admission(proposal, CONTEXT, _EMPTY_FINDING)
    assert first == second
    assert _checksum(first) == _checksum(second)
