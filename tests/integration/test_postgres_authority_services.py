"""Live PostgreSQL coverage for U7.2 authority lifecycle services."""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread

import pytest
from sqlalchemy import event, inspect, text

from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    AuthorityReasonCode,
    AuthorityScope,
    OperatorReference,
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
    list_capability_grants,
    read_authority_chain,
    record_approval_decision,
    revoke_capability_grant,
)
from orbitmind.persistence.authority_repository import SqlAlchemyAuthorityRepository
from orbitmind.persistence.database import Database

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

T0 = datetime(2026, 7, 19, tzinfo=UTC)
OWNER_A = "owner-piyush-01"
OWNER_B = "owner-second-02"
OPERATOR = OperatorReference(subject_id="operator-piyush-1")
SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-main")
POLICY = "authority-policy-v1"

_TABLES = (
    "authority_evaluations",
    "authority_revocations",
    "authority_capability_grants",
    "authority_approval_decisions",
    "authority_approval_requests",
)


@pytest.fixture
def database() -> Iterator[Database]:
    assert _PG_URL is not None
    db = Database(_PG_URL)
    inspector = inspect(db.engine)
    missing = [table for table in _TABLES if not inspector.has_table(table)]
    if missing:
        pytest.skip(f"authority tables absent (run alembic upgrade head): {missing}")
    _truncate(db)
    try:
        yield db
    finally:
        _truncate(db)
        db.dispose()


def _truncate(database: Database) -> None:
    with database.engine.begin() as connection:
        for table in _TABLES:
            connection.execute(text(f"DELETE FROM {table}"))


def _request(owner: str = OWNER_A) -> CreateApprovalRequestCommand:
    return CreateApprovalRequestCommand(
        owner_id=owner,
        request_id="req-00000001",
        requested_by=owner,
        subject=SUBJECT,
        capability="repository_read",
        scope=SCOPE,
        purpose="Read one bounded PostgreSQL revision.",
        policy_version=POLICY,
        requested_at=T0 - timedelta(hours=1),
        valid_from=T0,
        expires_at=T0 + timedelta(days=30),
        idempotency_key="request-key-001",
    )


def _decision(
    owner: str = OWNER_A, outcome: ApprovalDecisionOutcome = ApprovalDecisionOutcome.APPROVED
) -> RecordApprovalDecisionCommand:
    return RecordApprovalDecisionCommand(
        owner_id=owner,
        decision_id="dec-00000001",
        request_id="req-00000001",
        decided_by=OPERATOR,
        outcome=outcome,
        decided_at=T0 - timedelta(minutes=30),
        reason="Recorded terminal decision for PostgreSQL coverage.",
        policy_version=POLICY,
        idempotency_key="decision-key-01",
    )


def _grant(owner: str = OWNER_A) -> IssueCapabilityGrantCommand:
    return IssueCapabilityGrantCommand(
        owner_id=owner,
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


def _evaluation(owner: str = OWNER_A) -> EvaluateAuthorityCommand:
    return EvaluateAuthorityCommand(
        owner_id=owner,
        evaluation_id="eval-00000001",
        request_id="req-00000001",
        decision_id="dec-00000001",
        grant_id="grant-00000001",
        subject=SUBJECT,
        capability="repository_read",
        scope=SCOPE,
        purpose="Read one bounded PostgreSQL revision.",
        policy_version=POLICY,
        evaluation_time=T0 + timedelta(days=1),
        idempotency_key="evaluation-key1",
    )


def _approved_chain(database: Database) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request())
        record_approval_decision(session=session, command=_decision())
        issue_capability_grant(session=session, command=_grant())


def test_authorized_and_revoked_evaluations_persist_on_postgres(database: Database) -> None:
    _approved_chain(database)
    with database.session() as session:
        authorized = evaluate_authority_command(session=session, command=_evaluation())
        revoke_capability_grant(
            session=session,
            command=RevokeCapabilityGrantCommand(
                owner_id=OWNER_A,
                revocation_id="rvk-00000001",
                grant_id="grant-00000001",
                revoked_by=OPERATOR.subject_id,
                effective_at=T0 + timedelta(days=2),
                recorded_at=T0,
                reason="Revoked for PostgreSQL service coverage.",
                policy_version=POLICY,
                idempotency_key="revocation-key1",
            ),
        )
        revoked = evaluate_authority_command(
            session=session,
            command=_evaluation(
                evaluation_id="eval-00000002",
                evaluation_time=T0 + timedelta(days=3),
                idempotency_key="evaluation-key2",
            ),
        )
    assert authorized.reason_code is AuthorityReasonCode.AUTHORIZED
    assert revoked.reason_code is AuthorityReasonCode.REVOKED


def test_rejected_and_approved_without_grant_fail_without_evaluation_on_postgres(
    database: Database,
) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request())
        record_approval_decision(
            session=session, command=_decision(outcome=ApprovalDecisionOutcome.REJECTED)
        )
        with pytest.raises(AuthorityDecisionRejectedError):
            issue_capability_grant(session=session, command=_grant())
        with pytest.raises(AuthorityDecisionRejectedError):
            evaluate_authority_command(session=session, command=_evaluation())
        assert read_authority_chain(session=session, owner_id=OWNER_A, request_id="req-00000001")


def test_approved_without_grant_fails_closed_then_explicit_issue_succeeds_on_postgres(
    database: Database,
) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request())
        record_approval_decision(session=session, command=_decision())
        with pytest.raises(AuthorityGrantNotFoundError):
            evaluate_authority_command(session=session, command=_evaluation())
        grant = issue_capability_grant(session=session, command=_grant())
        evaluation = evaluate_authority_command(session=session, command=_evaluation())
    assert grant.grant_id == "grant-00000001"
    assert evaluation.authorized is True


def test_owner_isolation_and_idempotency_replay_on_postgres(database: Database) -> None:
    with database.session() as session:
        first = create_approval_request(session=session, command=_request())
        assert create_approval_request(session=session, command=_request()) == first
        create_approval_request(session=session, command=_request(OWNER_B))
        with pytest.raises(IdempotencyConflictError):
            create_approval_request(
                session=session,
                command=_request().model_copy(update={"request_id": "req-00000002"}),
            )
        assert list_capability_grants(session=session, owner_id=OWNER_B) == ()


def test_terminal_decisions_serialize_per_request_on_postgres(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    with database.session() as session:
        create_approval_request(session=session, command=_request())

    original = SqlAlchemyAuthorityRepository.read_approval_request_for_update
    first_lock_acquired = Event()
    second_lock_query_started = Event()
    release_first = Event()
    second_finished = Event()
    lock_call_guard = Lock()
    lock_call_count = 0
    results: dict[str, object] = {}
    errors: dict[str, BaseException] = {}

    def observe_request_lock_query(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        if "authority_approval_requests" not in statement or "FOR UPDATE" not in statement:
            return
        nonlocal lock_call_count
        with lock_call_guard:
            lock_call_count += 1
            if lock_call_count == 2:
                second_lock_query_started.set()

    event.listen(database.engine, "before_cursor_execute", observe_request_lock_query)

    def blocking_request_lock(
        repository: SqlAlchemyAuthorityRepository, *, owner_id: str, request_id: str
    ):
        result = original(repository, owner_id=owner_id, request_id=request_id)
        if not first_lock_acquired.is_set():
            first_lock_acquired.set()
            assert release_first.wait(timeout=5)
        return result

    monkeypatch.setattr(
        SqlAlchemyAuthorityRepository,
        "read_approval_request_for_update",
        blocking_request_lock,
    )

    def record(name: str, command: RecordApprovalDecisionCommand) -> None:
        try:
            with database.session() as session:
                results[name] = record_approval_decision(session=session, command=command)
        except BaseException as error:  # pragma: no cover - asserted by parent thread
            errors[name] = error
        finally:
            if name == "rejected":
                second_finished.set()

    approved_worker = Thread(target=record, args=("approved", _decision()))
    rejected_worker = Thread(
        target=record,
        args=(
            "rejected",
            _decision(
                outcome=ApprovalDecisionOutcome.REJECTED,
            ).model_copy(
                update={
                    "decision_id": "dec-00000002",
                    "idempotency_key": "decision-key-02",
                    "reason": "Rejected concurrent terminal decision for serialization coverage.",
                }
            ),
        ),
    )
    approved_worker.start()
    assert first_lock_acquired.wait(timeout=2)
    rejected_worker.start()
    try:
        assert second_lock_query_started.wait(timeout=2)
        assert _wait_for_request_row_lock_wait(database)
        assert not second_finished.wait(timeout=0.2)
    finally:
        release_first.set()
    approved_worker.join(timeout=5)
    rejected_worker.join(timeout=5)
    event.remove(database.engine, "before_cursor_execute", observe_request_lock_query)

    assert not approved_worker.is_alive()
    assert not rejected_worker.is_alive()
    assert errors.keys() == {"rejected"}
    assert isinstance(errors["rejected"], AuthorityRequestAlreadyDecidedError)
    approved = results["approved"]
    assert isinstance(approved, ApprovalDecision)
    assert approved.outcome is ApprovalDecisionOutcome.APPROVED
    with database.session() as session:
        chain = read_authority_chain(session=session, owner_id=OWNER_A, request_id="req-00000001")
    assert chain is not None
    assert len(chain.approval_decisions) == 1


def _wait_for_request_row_lock_wait(database: Database, *, timeout_seconds: float = 2.0) -> bool:
    """Observe PostgreSQL's second backend waiting on the request-row lock."""

    deadline = time.monotonic() + timeout_seconds
    query = text(
        "SELECT EXISTS ("
        "SELECT 1 FROM pg_stat_activity "
        "WHERE wait_event_type = 'Lock' "
        "AND query ILIKE '%authority_approval_requests%' "
        "AND query ILIKE '%FOR UPDATE%'"
        ")"
    )
    while time.monotonic() < deadline:
        with database.engine.connect() as connection:
            if connection.scalar(query):
                return True
        time.sleep(0.02)
    return False
