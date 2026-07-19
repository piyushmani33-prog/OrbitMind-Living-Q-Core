"""Live PostgreSQL tests for durable U7 authority persistence (U7.1).

The disposable database must already be migrated to Alembic head. These tests
never call ORM ``create_all()``, so the migration remains the schema authority.
Run with a DISPOSABLE database::

    ORBITMIND_TEST_POSTGRES_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/disposable \
        python -m pytest -m postgres tests/integration/test_postgres_authority.py -v
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from threading import Event, Thread

import pytest
from sqlalchemy import inspect, text

from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityEvaluationDecision,
    AuthorityEvaluationRequest,
    AuthorityScope,
    CapabilityGrant,
    OperatorReference,
    RevocationRecord,
    ScopeConstraint,
    SubjectReference,
    SubjectType,
    ValidityWindow,
)
from orbitmind.authority.evaluation import evaluate_authority
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.persistence.authority_models import AuthorityEvaluationRow
from orbitmind.persistence.authority_repository import (
    AuthorityCausalityError,
    AuthorityRecordCorruptError,
    SqlAlchemyAuthorityRepository,
)
from orbitmind.persistence.database import Database

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

T0 = datetime(2026, 7, 18, tzinfo=UTC)
WINDOW = ValidityWindow(valid_from=T0, expires_at=T0 + timedelta(days=30))
SUBJECT = SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-dev-0001")
OPERATOR = OperatorReference(subject_id="operator-piyush-1")
SCOPE = AuthorityScope(
    resource_type="repository",
    resource_id="orbitmind-main",
    constraints=(ScopeConstraint(name="ref", value="rev-abc123"),),
)
OWNER_A = "owner-piyush-01"
OWNER_B = "owner-second-02"
PURPOSE = "Read one pinned revision for review evidence."
POLICY = "authority-policy-v1"

_TABLES = (
    "authority_evaluations",
    "authority_revocations",
    "authority_capability_grants",
    "authority_approval_decisions",
    "authority_approval_requests",
)


def _request(owner: str = OWNER_A, request_id: str = "req-00000001") -> ApprovalRequest:
    return ApprovalRequest(
        request_id=request_id,
        owner_id=owner,
        requested_by="owner-piyush-01",
        subject=SUBJECT,
        capability="repository_read",
        scope=SCOPE,
        purpose=PURPOSE,
        policy_version=POLICY,
        requested_at=T0 - timedelta(hours=1),
        validity=WINDOW,
    )


def _decision(
    owner: str = OWNER_A, outcome: ApprovalDecisionOutcome = ApprovalDecisionOutcome.APPROVED
) -> ApprovalDecision:
    base = _request(owner)
    return ApprovalDecision(
        decision_id="dec-00000001",
        request_id=base.request_id,
        owner_id=owner,
        decided_by=OPERATOR,
        outcome=outcome,
        decided_at=T0 - timedelta(minutes=30),
        reason="Approved for one bounded review.",
        subject=base.subject,
        capability=base.capability,
        scope=base.scope,
        purpose=base.purpose,
        policy_version=base.policy_version,
        validity=base.validity,
    )


def _grant(owner: str = OWNER_A) -> CapabilityGrant:
    dec = _decision(owner)
    return CapabilityGrant(
        grant_id="grant-00000001",
        owner_id=owner,
        request_id=dec.request_id,
        decision_id=dec.decision_id,
        issued_by=OPERATOR,
        issued_at=T0 - timedelta(minutes=15),
        subject=dec.subject,
        capability=dec.capability,
        scope=dec.scope,
        purpose=dec.purpose,
        policy_version=dec.policy_version,
        validity=dec.validity,
    )


def _revocation(
    revocation_id: str = "rvk-00000001", *, effective_at: datetime = T0
) -> RevocationRecord:
    return RevocationRecord(
        revocation_id=revocation_id,
        grant_id="grant-00000001",
        owner_id=OWNER_A,
        revoked_by=OPERATOR.subject_id,
        effective_at=effective_at,
        recorded_at=effective_at,
        reason="Revoked for PostgreSQL stored-chain coverage.",
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


def _truncate(db: Database) -> None:
    with db.engine.begin() as conn:
        for table in _TABLES:
            conn.execute(text(f"DELETE FROM {table}"))


def _seed(repo: SqlAlchemyAuthorityRepository, owner: str = OWNER_A) -> None:
    repo.append_approval_request(_request(owner), idempotency_key="k-req")
    repo.append_approval_decision(_decision(owner), idempotency_key="k-dec")
    repo.append_capability_grant(_grant(owner), idempotency_key="k-grant")


def test_migration_head_and_tables_present(database: Database) -> None:
    inspector = inspect(database.engine)
    for table in _TABLES:
        assert inspector.has_table(table)


def test_full_chain_round_trips_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
        request = _evaluation()
        stored = repo.append_evaluation_record(
            request, evaluate_authority(request), idempotency_key="k-eval"
        )
        assert stored.authorized is True
    with database.session() as session:
        repo = SqlAlchemyAuthorityRepository(session)
        assert repo.get_capability_grant(owner_id=OWNER_A, grant_id="grant-00000001") == _grant()
        chain = repo.read_authority_chain(owner_id=OWNER_A, grant_id="grant-00000001")
        assert chain is not None and chain.grant == _grant()
        assert len(chain.evaluations) == 1


def test_owner_isolation_and_uniqueness_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo, OWNER_A)
        _seed(repo, OWNER_B)  # same ids + same idempotency keys, different owner
        assert repo.get_capability_grant(owner_id=OWNER_A, grant_id="grant-00000001") == _grant(
            OWNER_A
        )
        assert repo.get_capability_grant(owner_id=OWNER_B, grant_id="grant-00000001") == _grant(
            OWNER_B
        )
        assert len(repo.list_capability_grants(owner_id=OWNER_A)) == 1
        assert len(repo.list_capability_grants(owner_id=OWNER_B)) == 1


def test_idempotent_replay_and_conflict_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        first = repo.append_approval_request(_request(), idempotency_key="k")
        second = repo.append_approval_request(_request(), idempotency_key="k")
        assert first == second
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        with pytest.raises(IdempotencyConflictError):
            repo.append_approval_request(_request(request_id="req-00000002"), idempotency_key="k")


def test_append_only_and_causality_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(), idempotency_key="k-req")
        repo.append_approval_decision(
            _decision(outcome=ApprovalDecisionOutcome.REJECTED), idempotency_key="k-dec"
        )
        with pytest.raises(AuthorityCausalityError):
            repo.append_capability_grant(_grant(), idempotency_key="k-grant")
    with database.session() as session:
        repo = SqlAlchemyAuthorityRepository(session)
        assert repo.list_capability_grants(owner_id=OWNER_A) == ()


def test_foreign_key_restrict_blocks_orphan_delete(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
    # RESTRICT: a request that a grant/decision references cannot be deleted.
    with pytest.raises(Exception), database.engine.begin() as conn:  # noqa: B017
        conn.execute(
            text("DELETE FROM authority_approval_requests WHERE id = :i"),
            {"i": "req-00000001"},
        )


def test_timestamps_round_trip_utc_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
        revocation = RevocationRecord(
            revocation_id="rvk-00000001",
            grant_id="grant-00000001",
            owner_id=OWNER_A,
            revoked_by="owner-piyush-01",
            effective_at=T0 + timedelta(days=2),
            recorded_at=T0 + timedelta(days=2, hours=1),
            reason="Revoked for test.",
        )
        stored = repo.append_revocation(revocation, idempotency_key="k-rvk")
        assert stored == revocation
        assert stored.effective_at.tzinfo == UTC


def _evaluation(owner: str = OWNER_A, **overrides: object) -> AuthorityEvaluationRequest:
    values: dict[str, object] = {
        "evaluation_id": "eval-0000001",
        "owner_id": owner,
        "evaluation_time": T0 + timedelta(days=1),
        "subject": SUBJECT,
        "capability": "repository_read",
        "scope": SCOPE,
        "purpose": PURPOSE,
        "policy_version": POLICY,
        "approval_request": _request(owner),
        "approval_decision": _decision(owner),
        "grant": _grant(owner),
    }
    values.update(overrides)
    return AuthorityEvaluationRequest(**values)


def test_omitted_effective_revocation_is_rejected_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        omitted = _evaluation()
        with pytest.raises(AuthorityCausalityError):
            repo.append_evaluation_record(
                omitted, evaluate_authority(omitted), idempotency_key="k-eval"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id) == ()


def test_substituted_same_owner_grant_is_rejected_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
        substituted = _grant().model_copy(update={"capability": "repository_write"})
        request = _evaluation(grant=substituted)
        with pytest.raises(AuthorityCausalityError):
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key="k-eval-substituted"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=substituted.grant_id) == ()


def test_rejected_chain_does_not_change_postgres_transaction(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        omitted = _evaluation()
        with pytest.raises(AuthorityCausalityError):
            repo.append_evaluation_record(
                omitted, evaluate_authority(omitted), idempotency_key="k-bad"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id) == ()


def test_complete_stored_chain_persists_on_postgres(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        request = _evaluation(revocations=(revocation,))
        stored = repo.append_evaluation_record(
            request, evaluate_authority(request), idempotency_key="k-eval"
        )
        assert stored.authorized is False
        assert len(repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id)) == 1


def test_revocation_first_serializes_and_rejects_stale_evaluation(database: Database) -> None:
    with database.session() as session, session.begin():
        _seed(SqlAlchemyAuthorityRepository(session))

    revocation = _revocation()
    stale_request = _evaluation()
    evaluation_attempted = Event()
    evaluation_finished = Event()
    thread_errors: list[BaseException] = []
    outcome: dict[str, object] = {}

    def append_evaluation() -> None:
        try:
            with database.session() as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                repo = SqlAlchemyAuthorityRepository(session)
                evaluation_attempted.set()
                with pytest.raises(AuthorityCausalityError):
                    repo.append_evaluation_record(
                        stale_request,
                        evaluate_authority(stale_request),
                        idempotency_key="k-stale",
                    )
                corrected_request = _evaluation(
                    evaluation_id="eval-0000002", revocations=(revocation,)
                )
                outcome["corrected"] = repo.append_evaluation_record(
                    corrected_request,
                    evaluate_authority(corrected_request),
                    idempotency_key="k-corrected",
                )
        except BaseException as error:  # pragma: no cover - asserted by the parent thread
            thread_errors.append(error)
        finally:
            evaluation_finished.set()

    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo._lock_owner_grant_for_authority_append(OWNER_A, revocation.grant_id)
        worker = Thread(target=append_evaluation)
        worker.start()
        assert evaluation_attempted.wait(timeout=2)
        assert not evaluation_finished.wait(timeout=0.2)
        repo.append_revocation(revocation, idempotency_key="k-rvk")

    assert evaluation_finished.wait(timeout=5)
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert thread_errors == []
    corrected = outcome["corrected"]
    assert isinstance(corrected, AuthorityEvaluationDecision)
    assert corrected.authorized is False

    with database.session() as session:
        repo = SqlAlchemyAuthorityRepository(session)
        assert session.get(AuthorityEvaluationRow, (stale_request.evaluation_id, OWNER_A)) is None
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id) == (corrected,)


def test_evaluation_first_serializes_before_later_revocation(database: Database) -> None:
    with database.session() as session, session.begin():
        _seed(SqlAlchemyAuthorityRepository(session))

    revocation = _revocation()
    revocation_attempted = Event()
    revocation_finished = Event()
    thread_errors: list[BaseException] = []

    def append_revocation() -> None:
        try:
            with database.session() as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout = '5s'"))
                revocation_attempted.set()
                SqlAlchemyAuthorityRepository(session).append_revocation(
                    revocation, idempotency_key="k-rvk"
                )
        except BaseException as error:  # pragma: no cover - asserted by the parent thread
            thread_errors.append(error)
        finally:
            revocation_finished.set()

    request = _evaluation()
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo._lock_owner_grant_for_authority_append(OWNER_A, request.grant.grant_id)
        worker = Thread(target=append_revocation)
        worker.start()
        assert revocation_attempted.wait(timeout=2)
        assert not revocation_finished.wait(timeout=0.2)
        first = repo.append_evaluation_record(
            request, evaluate_authority(request), idempotency_key="k-eval-first"
        )
        assert first.authorized is True

    assert revocation_finished.wait(timeout=5)
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert thread_errors == []

    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id) == (first,)
        later_request = _evaluation(evaluation_id="eval-0000002", revocations=(revocation,))
        later = repo.append_evaluation_record(
            later_request, evaluate_authority(later_request), idempotency_key="k-eval-later"
        )
        assert later.authorized is False


def test_grant_lock_is_exact_and_unrelated_owner_grant_does_not_block(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed(repo, OWNER_A)
        _seed(repo, OWNER_B)

    unrelated_finished = Event()
    thread_errors: list[BaseException] = []

    def lock_unrelated_grant() -> None:
        try:
            with database.session() as session, session.begin():
                session.execute(text("SET LOCAL lock_timeout = '2s'"))
                SqlAlchemyAuthorityRepository(session)._lock_owner_grant_for_authority_append(
                    OWNER_B, "grant-00000001"
                )
        except BaseException as error:  # pragma: no cover - asserted by the parent thread
            thread_errors.append(error)
        finally:
            unrelated_finished.set()

    with database.session() as session, session.begin():
        SqlAlchemyAuthorityRepository(session)._lock_owner_grant_for_authority_append(
            OWNER_A, "grant-00000001"
        )
        worker = Thread(target=lock_unrelated_grant)
        worker.start()
        assert unrelated_finished.wait(timeout=2)

    worker.join(timeout=1)
    assert not worker.is_alive()
    assert thread_errors == []


def test_tampered_evaluation_projection_fails_closed_on_postgres(database: Database) -> None:
    with database.session() as session:
        with session.begin():
            repo = SqlAlchemyAuthorityRepository(session)
            _seed(repo)
            request = _evaluation()
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key="k-eval"
            )
        with session.begin():
            row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
            assert row is not None
            row.allowed = False
        with pytest.raises(AuthorityRecordCorruptError, match="projection mismatch"):
            SqlAlchemyAuthorityRepository(session).list_evaluations(
                owner_id=OWNER_A, grant_id="grant-00000001"
            )
