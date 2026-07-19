"""Transaction-boundary regressions for U7.2 lifecycle commands."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orbitmind.authority.contracts import (
    ApprovalDecisionOutcome,
    AuthorityScope,
    OperatorReference,
    SubjectReference,
    SubjectType,
)
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.orchestration.authority_lifecycle import (
    AuthorityDecisionRejectedError,
    AuthorityLifecycleTransactionError,
    CreateApprovalRequestCommand,
    EvaluateAuthorityCommand,
    IssueCapabilityGrantCommand,
    RecordApprovalDecisionCommand,
    create_approval_request,
    evaluate_authority_command,
    issue_capability_grant,
    list_capability_grants,
    record_approval_decision,
)
from orbitmind.persistence.authority_repository import SqlAlchemyAuthorityRepository
from orbitmind.persistence.database import Database

T0 = datetime(2026, 7, 19, tzinfo=UTC)
OWNER = "owner-piyush-01"
OPERATOR = OperatorReference(subject_id="operator-piyush-1")
SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-main")
POLICY = "authority-policy-v1"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(f"sqlite:///{tmp_path / 'authority-service-transactions.db'}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _request(
    request_id: str = "req-00000001", key: str = "request-key-001"
) -> CreateApprovalRequestCommand:
    return CreateApprovalRequestCommand(
        owner_id=OWNER,
        request_id=request_id,
        requested_by=OWNER,
        subject=SUBJECT,
        capability="repository_read",
        scope=SCOPE,
        purpose="Read one bounded repository revision.",
        policy_version=POLICY,
        requested_at=T0 - timedelta(hours=1),
        valid_from=T0,
        expires_at=T0 + timedelta(days=30),
        idempotency_key=key,
    )


def _decision(
    outcome: ApprovalDecisionOutcome = ApprovalDecisionOutcome.APPROVED,
) -> RecordApprovalDecisionCommand:
    return RecordApprovalDecisionCommand(
        owner_id=OWNER,
        decision_id="dec-00000001",
        request_id="req-00000001",
        decided_by=OPERATOR,
        outcome=outcome,
        decided_at=T0 - timedelta(minutes=30),
        reason="Recorded terminal decision for transaction coverage.",
        policy_version=POLICY,
        idempotency_key="decision-key-01",
    )


def _grant() -> IssueCapabilityGrantCommand:
    return IssueCapabilityGrantCommand(
        owner_id=OWNER,
        grant_id="grant-00000001",
        request_id="req-00000001",
        decision_id="dec-00000001",
        issued_by=OPERATOR,
        issued_at=T0 - timedelta(minutes=15),
        valid_from=T0,
        expires_at=T0 + timedelta(days=30),
        policy_version=POLICY,
        idempotency_key="grant-key-0001",
    )


def _evaluation() -> EvaluateAuthorityCommand:
    return EvaluateAuthorityCommand(
        owner_id=OWNER,
        evaluation_id="eval-00000001",
        request_id="req-00000001",
        decision_id="dec-00000001",
        grant_id="grant-00000001",
        subject=SUBJECT,
        capability="repository_read",
        scope=SCOPE,
        purpose="Read one bounded repository revision.",
        policy_version=POLICY,
        evaluation_time=T0 + timedelta(days=1),
        idempotency_key="evaluation-key1",
    )


def test_service_rejects_active_caller_transaction_without_committing_caller_work(
    database: Database,
) -> None:
    with database.session() as session:
        with session.begin():
            repo = SqlAlchemyAuthorityRepository(session)
            stored = repo.append_approval_request(
                _domain_request(), idempotency_key="caller-owned-key"
            )
            with pytest.raises(AuthorityLifecycleTransactionError):
                create_approval_request(session=session, command=_request("req-00000002"))
            assert repo.get_approval_request(owner_id=OWNER, request_id=stored.request_id) == stored
        create_approval_request(session=session, command=_request("req-00000002"))
    with database.session() as session:
        assert len(list_capability_grants(session=session, owner_id=OWNER)) == 0


def test_rejected_grant_and_evaluation_failures_leave_session_usable(database: Database) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request())
        record_approval_decision(
            session=session, command=_decision(ApprovalDecisionOutcome.REJECTED)
        )
        with pytest.raises(AuthorityDecisionRejectedError):
            issue_capability_grant(session=session, command=_grant())
        with pytest.raises(AuthorityDecisionRejectedError):
            evaluate_authority_command(session=session, command=_evaluation())
        assert list_capability_grants(session=session, owner_id=OWNER) == ()
        assert len(list_capability_grants(session=session, owner_id=OWNER)) == 0


def test_idempotency_conflict_preserves_prior_truth_and_session_recovers(
    database: Database,
) -> None:
    with database.session() as session:
        first = create_approval_request(session=session, command=_request())
        with pytest.raises(IdempotencyConflictError):
            create_approval_request(
                session=session,
                command=_request(request_id="req-00000002", key="request-key-001"),
            )
        replay = create_approval_request(session=session, command=_request())
    assert replay == first


def _domain_request():
    """Keep the caller-owned transaction test independent of the service command."""

    from orbitmind.authority.contracts import ApprovalRequest, ValidityWindow

    return ApprovalRequest(
        request_id="req-00000003",
        owner_id=OWNER,
        requested_by=OWNER,
        subject=SUBJECT,
        capability="repository_read",
        scope=SCOPE,
        purpose="Read one caller-owned transaction revision.",
        policy_version=POLICY,
        requested_at=T0 - timedelta(hours=1),
        validity=ValidityWindow(valid_from=T0, expires_at=T0 + timedelta(days=30)),
    )
