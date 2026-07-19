"""Offline SQLite coverage for the U7.2 authority lifecycle services."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select

from orbitmind.authority.contracts import (
    ApprovalDecisionOutcome,
    AuthorityReasonCode,
    AuthorityScope,
    OperatorReference,
    ScopeConstraint,
    SubjectReference,
    SubjectType,
)
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.orchestration.authority_lifecycle import (
    AuthorityDecisionRejectedError,
    AuthorityGrantNotFoundError,
    AuthorityRequestAlreadyDecidedError,
    CreateApprovalRequestCommand,
    EvaluateAuthorityCommand,
    IssueCapabilityGrantCommand,
    RecordApprovalDecisionCommand,
    RevokeCapabilityGrantCommand,
    create_approval_request,
    evaluate_authority_command,
    issue_capability_grant,
    list_approval_requests,
    list_evaluations_for_grant,
    read_authority_chain,
    record_approval_decision,
    revoke_capability_grant,
)
from orbitmind.persistence.authority_models import AuthorityEvaluationRow
from orbitmind.persistence.database import Database

T0 = datetime(2026, 7, 19, tzinfo=UTC)
OWNER_A = "owner-piyush-01"
OWNER_B = "owner-second-02"
REQUESTED_BY = "owner-piyush-01"
OPERATOR = OperatorReference(subject_id="operator-piyush-1")
SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
OTHER_SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0002")
SCOPE = AuthorityScope(
    resource_type="repository",
    resource_id="orbitmind-main",
    constraints=(ScopeConstraint(name="ref", value="rev-abc123"),),
)
OTHER_SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-docs")
CAPABILITY = "repository_read"
PURPOSE = "Read one pinned revision for review evidence."
POLICY = "authority-policy-v1"
OTHER_POLICY = "authority-policy-v2"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(f"sqlite:///{tmp_path / 'authority-services.db'}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _request_command(owner: str = OWNER_A, **overrides: Any) -> CreateApprovalRequestCommand:
    values: dict[str, Any] = {
        "owner_id": owner,
        "request_id": "req-00000001",
        "requested_by": REQUESTED_BY if owner == OWNER_A else OWNER_B,
        "subject": SUBJECT,
        "capability": CAPABILITY,
        "scope": SCOPE,
        "purpose": PURPOSE,
        "policy_version": POLICY,
        "requested_at": T0 - timedelta(hours=1),
        "valid_from": T0,
        "expires_at": T0 + timedelta(days=30),
        "idempotency_key": "request-key-001",
    }
    values.update(overrides)
    return CreateApprovalRequestCommand(**values)


def _decision_command(owner: str = OWNER_A, **overrides: Any) -> RecordApprovalDecisionCommand:
    values: dict[str, Any] = {
        "owner_id": owner,
        "decision_id": "dec-00000001",
        "request_id": "req-00000001",
        "decided_by": OPERATOR,
        "outcome": ApprovalDecisionOutcome.APPROVED,
        "decided_at": T0 - timedelta(minutes=30),
        "reason": "Approved for one bounded review.",
        "policy_version": POLICY,
        "idempotency_key": "decision-key-01",
    }
    values.update(overrides)
    return RecordApprovalDecisionCommand(**values)


def _grant_command(owner: str = OWNER_A, **overrides: Any) -> IssueCapabilityGrantCommand:
    values: dict[str, Any] = {
        "owner_id": owner,
        "grant_id": "grant-00000001",
        "request_id": "req-00000001",
        "decision_id": "dec-00000001",
        "issued_by": OPERATOR,
        "issued_at": T0 - timedelta(minutes=15),
        "valid_from": T0,
        "expires_at": T0 + timedelta(days=30),
        "policy_version": POLICY,
        "idempotency_key": "grant-key-0001",
    }
    values.update(overrides)
    return IssueCapabilityGrantCommand(**values)


def _evaluation_command(owner: str = OWNER_A, **overrides: Any) -> EvaluateAuthorityCommand:
    values: dict[str, Any] = {
        "owner_id": owner,
        "evaluation_id": "eval-00000001",
        "request_id": "req-00000001",
        "decision_id": "dec-00000001",
        "grant_id": "grant-00000001",
        "subject": SUBJECT,
        "capability": CAPABILITY,
        "scope": SCOPE,
        "purpose": PURPOSE,
        "policy_version": POLICY,
        "evaluation_time": T0 + timedelta(days=1),
        "idempotency_key": "evaluation-key1",
    }
    values.update(overrides)
    return EvaluateAuthorityCommand(**values)


def _create_approved_chain(database: Database) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request_command())
        record_approval_decision(session=session, command=_decision_command())
        issue_capability_grant(session=session, command=_grant_command())


def _evaluation_row_count(database: Database) -> int:
    with database.session() as session:
        return session.scalar(select(func.count()).select_from(AuthorityEvaluationRow)) or 0


def test_commands_are_strict_closed_and_reject_naive_timestamps() -> None:
    with pytest.raises(PydanticValidationError):
        _request_command(unknown_field="not-allowed")
    with pytest.raises(PydanticValidationError):
        _request_command(requested_at=datetime(2026, 7, 19))
    with pytest.raises(PydanticValidationError):
        _request_command(expires_at=T0)
    with pytest.raises(PydanticValidationError):
        _request_command(purpose="Read https://example.invalid/hidden")
    with pytest.raises(PydanticValidationError):
        _decision_command(policy_version="authority..policy-v1")
    with pytest.raises(PydanticValidationError):
        _grant_command(expires_at=T0 + timedelta(days=367))
    assert "subject" not in IssueCapabilityGrantCommand.model_fields
    assert "capability" not in IssueCapabilityGrantCommand.model_fields
    assert "scope" not in IssueCapabilityGrantCommand.model_fields
    assert "purpose" not in IssueCapabilityGrantCommand.model_fields


def test_request_replay_conflict_and_non_authoritative_read_state(database: Database) -> None:
    command = _request_command()
    with database.session() as session:
        first = create_approval_request(session=session, command=command)
        second = create_approval_request(session=session, command=command)
        assert second == first
        with pytest.raises(IdempotencyConflictError):
            create_approval_request(
                session=session,
                command=_request_command(request_id="req-00000002"),
            )
        chain = read_authority_chain(session=session, owner_id=OWNER_A, request_id=first.request_id)
    assert chain is not None
    assert chain.approval_request == first
    assert chain.approval_decisions == ()
    assert chain.capability_grants == ()
    assert chain.revocations == ()
    assert chain.evaluations == ()


def test_rejected_decision_is_terminal_denial_evidence_without_grant_or_evaluation(
    database: Database,
) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request_command())
        rejected_command = _decision_command(
            outcome=ApprovalDecisionOutcome.REJECTED,
            reason="Rejected because the bounded review is not approved.",
        )
        rejected = record_approval_decision(session=session, command=rejected_command)
        assert record_approval_decision(session=session, command=rejected_command) == rejected
        with pytest.raises(AuthorityDecisionRejectedError) as grant_error:
            issue_capability_grant(session=session, command=_grant_command())
        assert grant_error.value.code == "authority_decision_rejected"
        with pytest.raises(AuthorityDecisionRejectedError) as evaluation_error:
            evaluate_authority_command(session=session, command=_evaluation_command())
        assert evaluation_error.value.code == "authority_decision_rejected"
        with pytest.raises(AuthorityRequestAlreadyDecidedError):
            record_approval_decision(
                session=session,
                command=_decision_command(
                    decision_id="dec-00000002",
                    idempotency_key="decision-key-02",
                    outcome=ApprovalDecisionOutcome.APPROVED,
                ),
            )
        chain = read_authority_chain(session=session, owner_id=OWNER_A, request_id="req-00000001")
    assert rejected.outcome is ApprovalDecisionOutcome.REJECTED
    assert chain is not None
    assert chain.approval_decisions == (rejected,)
    assert chain.capability_grants == ()
    assert chain.evaluations == ()
    assert _evaluation_row_count(database) == 0


def test_approved_without_grant_fails_closed_then_explicit_grant_can_be_evaluated(
    database: Database,
) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request_command())
        record_approval_decision(session=session, command=_decision_command())
        with pytest.raises(AuthorityGrantNotFoundError) as error:
            evaluate_authority_command(session=session, command=_evaluation_command())
        assert error.value.code == "authority_grant_not_found"
        assert _evaluation_row_count(database) == 0
        grant = issue_capability_grant(session=session, command=_grant_command())
        decision = evaluate_authority_command(session=session, command=_evaluation_command())
    assert grant.grant_id == "grant-00000001"
    assert decision.authorized is True
    assert decision.reason_code is AuthorityReasonCode.AUTHORIZED


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"subject": OTHER_SUBJECT}, AuthorityReasonCode.SUBJECT_MISMATCH),
        ({"capability": "repository_write"}, AuthorityReasonCode.CAPABILITY_MISMATCH),
        ({"scope": OTHER_SCOPE}, AuthorityReasonCode.SCOPE_MISMATCH),
        ({"purpose": "Read a different bounded revision."}, AuthorityReasonCode.PURPOSE_MISMATCH),
        ({"policy_version": OTHER_POLICY}, AuthorityReasonCode.POLICY_VERSION_MISMATCH),
        ({"evaluation_time": T0 - timedelta(minutes=10)}, AuthorityReasonCode.NOT_YET_VALID),
        ({"evaluation_time": T0 + timedelta(days=30)}, AuthorityReasonCode.EXPIRED),
        ({"delegation_requested": True}, AuthorityReasonCode.DELEGATION_PROHIBITED),
    ],
)
def test_grant_backed_denied_evaluations_persist(
    database: Database, overrides: dict[str, Any], reason: AuthorityReasonCode
) -> None:
    _create_approved_chain(database)
    command = _evaluation_command(**overrides)
    with database.session() as session:
        result = evaluate_authority_command(session=session, command=command)
        stored = list_evaluations_for_grant(
            session=session, owner_id=OWNER_A, grant_id="grant-00000001"
        )
    assert result.authorized is False
    assert result.reason_code is reason
    assert stored == (result,)


def test_revocations_are_append_only_and_earliest_effective_record_controls_evaluation(
    database: Database,
) -> None:
    _create_approved_chain(database)
    with database.session() as session:
        later = revoke_capability_grant(
            session=session,
            command=RevokeCapabilityGrantCommand(
                owner_id=OWNER_A,
                revocation_id="rvk-00000002",
                grant_id="grant-00000001",
                revoked_by=OPERATOR.subject_id,
                effective_at=T0 + timedelta(days=5),
                recorded_at=T0,
                reason="Later revocation observation for deterministic ordering.",
                policy_version=POLICY,
                idempotency_key="revocation-key2",
            ),
        )
        earlier = revoke_capability_grant(
            session=session,
            command=RevokeCapabilityGrantCommand(
                owner_id=OWNER_A,
                revocation_id="rvk-00000001",
                grant_id="grant-00000001",
                revoked_by=OPERATOR.subject_id,
                effective_at=T0 + timedelta(days=1),
                recorded_at=T0,
                reason="Earlier revocation observation for deterministic ordering.",
                policy_version=POLICY,
                idempotency_key="revocation-key1",
            ),
        )
        decision = evaluate_authority_command(
            session=session,
            command=_evaluation_command(evaluation_time=T0 + timedelta(days=7)),
        )
        chain = read_authority_chain(session=session, owner_id=OWNER_A, request_id="req-00000001")
    assert later != earlier
    assert decision.reason_code is AuthorityReasonCode.REVOKED
    assert chain is not None
    assert chain.revocations == (earlier, later)


def test_owner_scoping_is_non_disclosing_and_idempotency_is_per_owner(database: Database) -> None:
    with database.session() as session:
        stored_a = create_approval_request(session=session, command=_request_command())
        stored_b = create_approval_request(session=session, command=_request_command(OWNER_B))
        assert stored_a.owner_id == OWNER_A
        assert stored_b.owner_id == OWNER_B
        assert (
            read_authority_chain(session=session, owner_id=OWNER_B, request_id="req-00000001")
            is not None
        )
        assert (
            read_authority_chain(session=session, owner_id=OWNER_B, request_id="req-00000002")
            is None
        )
        assert list_approval_requests(session=session, owner_id="owner-third-03") == ()
        record_approval_decision(session=session, command=_decision_command(owner=OWNER_B))
        with pytest.raises(AuthorityGrantNotFoundError):
            evaluate_authority_command(session=session, command=_evaluation_command(owner=OWNER_B))


def test_grant_replay_and_conflict_preserve_stored_truth(database: Database) -> None:
    _create_approved_chain(database)
    command = _grant_command()
    with database.session() as session:
        first = issue_capability_grant(session=session, command=command)
        second = issue_capability_grant(session=session, command=command)
        assert first == second
        with pytest.raises(IdempotencyConflictError):
            issue_capability_grant(
                session=session,
                command=_grant_command(grant_id="grant-00000002"),
            )
        chain = read_authority_chain(session=session, owner_id=OWNER_A, request_id="req-00000001")
    assert chain is not None
    assert chain.capability_grants == (first,)
