"""U7.1 authority persistence tests (SQLite-backed, offline).

Covers mapping/round-trip, owner isolation, append-only behavior, causality,
idempotency/replay, transactional atomicity, fail-closed reads, and the
architecture boundary. Live-PostgreSQL equivalents run in
``tests/integration/test_postgres_authority.py`` under the ``postgres`` marker.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import orbitmind.authority
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
from orbitmind.authority.evaluation import evaluate_authority
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.persistence.authority_models import (
    AuthorityApprovalDecisionRow,
    AuthorityEvaluationRow,
)
from orbitmind.persistence.authority_repository import (
    _DECISION_IDENTITY,
    AuthorityCausalityError,
    AuthorityRecordCorruptError,
    SqlAlchemyAuthorityRepository,
    _identity,
)
from orbitmind.persistence.database import Database

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


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(f"sqlite:///{tmp_path / 'authority.db'}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _request(owner: str = OWNER_A, **overrides: Any) -> ApprovalRequest:
    values: dict[str, Any] = {
        "request_id": "req-00000001",
        "owner_id": owner,
        "requested_by": "owner-piyush-01",
        "subject": SUBJECT,
        "capability": "repository_read",
        "scope": SCOPE,
        "purpose": PURPOSE,
        "policy_version": POLICY,
        "requested_at": T0 - timedelta(hours=1),
        "validity": WINDOW,
    }
    values.update(overrides)
    return ApprovalRequest(**values)


def _decision(owner: str = OWNER_A, **overrides: Any) -> ApprovalDecision:
    base = _request(owner)
    values: dict[str, Any] = {
        "decision_id": "dec-00000001",
        "request_id": base.request_id,
        "owner_id": owner,
        "decided_by": OPERATOR,
        "outcome": ApprovalDecisionOutcome.APPROVED,
        "decided_at": T0 - timedelta(minutes=30),
        "reason": "Approved for one bounded review.",
        "subject": base.subject,
        "capability": base.capability,
        "scope": base.scope,
        "purpose": base.purpose,
        "policy_version": base.policy_version,
        "validity": base.validity,
    }
    values.update(overrides)
    return ApprovalDecision(**values)


def _grant(owner: str = OWNER_A, **overrides: Any) -> CapabilityGrant:
    dec = _decision(owner)
    values: dict[str, Any] = {
        "grant_id": "grant-00000001",
        "owner_id": owner,
        "request_id": dec.request_id,
        "decision_id": dec.decision_id,
        "issued_by": OPERATOR,
        "issued_at": T0 - timedelta(minutes=15),
        "subject": dec.subject,
        "capability": dec.capability,
        "scope": dec.scope,
        "purpose": dec.purpose,
        "policy_version": dec.policy_version,
        "validity": dec.validity,
    }
    values.update(overrides)
    return CapabilityGrant(**values)


def _evaluation(owner: str = OWNER_A, **overrides: Any) -> AuthorityEvaluationRequest:
    values: dict[str, Any] = {
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


def _seed_chain(repo: SqlAlchemyAuthorityRepository, owner: str = OWNER_A) -> None:
    repo.append_approval_request(_request(owner), idempotency_key="k-req")
    repo.append_approval_decision(_decision(owner), idempotency_key="k-dec")
    repo.append_capability_grant(_grant(owner), idempotency_key="k-grant")


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
        reason="Revoked for stored-chain completeness coverage.",
    )


# --- mapping / round-trip ----------------------------------------------------


def test_each_contract_round_trips_through_persistence(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        stored_request = repo.append_approval_request(_request(), idempotency_key="k-req")
        stored_decision = repo.append_approval_decision(_decision(), idempotency_key="k-dec")
        stored_grant = repo.append_capability_grant(_grant(), idempotency_key="k-grant")
        assert stored_request == _request()
        assert stored_decision == _decision()
        assert stored_grant == _grant()
    with database.session() as session:
        repo = SqlAlchemyAuthorityRepository(session)
        assert repo.get_approval_request(owner_id=OWNER_A, request_id="req-00000001") == _request()
        assert (
            repo.get_approval_decision(owner_id=OWNER_A, decision_id="dec-00000001") == _decision()
        )
        assert repo.get_capability_grant(owner_id=OWNER_A, grant_id="grant-00000001") == _grant()


def test_utc_values_round_trip_and_enums_preserved(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        stored = repo.get_capability_grant(owner_id=OWNER_A, grant_id="grant-00000001")
        assert stored is not None
    assert stored.issued_at == T0 - timedelta(minutes=15)
    assert stored.issued_at.tzinfo == UTC
    assert stored.delegation.value == "prohibited"
    assert stored.validity.valid_from == T0


def test_evaluation_record_persists_allowed_and_reason(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        request = _evaluation()
        decision = evaluate_authority(request)
        stored = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        assert stored == decision
        assert stored.authorized is True
        evaluations = repo.list_evaluations(owner_id=OWNER_A, grant_id="grant-00000001")
        assert evaluations == (decision,)


def test_authority_chain_projection_is_owner_scoped_and_complete(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        request = _evaluation()
        repo.append_evaluation_record(request, evaluate_authority(request), idempotency_key="k-ev")
        chain = repo.read_authority_chain(owner_id=OWNER_A, grant_id="grant-00000001")
        assert chain is not None
        assert chain.grant == _grant()
        assert chain.approval_decision == _decision()
        assert chain.approval_request == _request()
        assert len(chain.evaluations) == 1
        assert repo.read_authority_chain(owner_id=OWNER_B, grant_id="grant-00000001") is None


# --- owner isolation ---------------------------------------------------------


def test_owner_cannot_read_another_owners_records(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo, OWNER_A)
        assert repo.get_capability_grant(owner_id=OWNER_B, grant_id="grant-00000001") is None
        assert repo.get_approval_request(owner_id=OWNER_B, request_id="req-00000001") is None
        assert repo.list_capability_grants(owner_id=OWNER_B) == ()
        # Owner B's not-found is indistinguishable from truly absent (both None).
        assert repo.get_capability_grant(owner_id=OWNER_B, grant_id="grant-00000009") is None


def test_owner_cannot_link_a_decision_to_another_owners_request(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(OWNER_A), idempotency_key="k-req")
        # Owner B decides against a request id that only exists for owner A.
        with pytest.raises(AuthorityCausalityError):
            repo.append_approval_decision(_decision(OWNER_B), idempotency_key="k-dec")


def test_same_idempotency_key_isolated_across_owners(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(OWNER_A), idempotency_key="shared-key")
        repo.append_approval_request(
            _request(OWNER_B, requested_by="owner-second-02"), idempotency_key="shared-key"
        )
        assert repo.get_approval_request(owner_id=OWNER_A, request_id="req-00000001") is not None
        assert repo.get_approval_request(owner_id=OWNER_B, request_id="req-00000001") is not None


# --- append-only -------------------------------------------------------------


def test_repository_exposes_no_update_or_delete_verbs() -> None:
    public = {name for name in dir(SqlAlchemyAuthorityRepository) if not name.startswith("_")}
    forbidden = {
        "update",
        "delete",
        "remove",
        "approve",
        "reject",
        "issue_grant",
        "issue",
        "evaluate",
        "execute",
        "revoke",
    }
    assert not (public & forbidden)
    assert all(name.startswith(("append_", "get_", "list_", "read_")) for name in public), public


def test_duplicate_id_is_rejected(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(), idempotency_key="k-req-1")
        # Same request id, different idempotency key + different payload → conflict.
        with pytest.raises(IdempotencyConflictError):
            repo.append_approval_request(
                _request(requested_by="agent-dev-0002"), idempotency_key="k-req-2"
            )


def test_rejected_decision_row_is_never_changed_to_approved(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(), idempotency_key="k-req")
        rejected = _decision(outcome=ApprovalDecisionOutcome.REJECTED)
        repo.append_approval_decision(rejected, idempotency_key="k-dec")
        stored = repo.get_approval_decision(owner_id=OWNER_A, decision_id="dec-00000001")
        assert stored is not None and stored.outcome is ApprovalDecisionOutcome.REJECTED
        # Re-appending an "approved" decision with the same id fails closed.
        with pytest.raises(IdempotencyConflictError):
            repo.append_approval_decision(_decision(), idempotency_key="k-dec-2")


def test_grant_remains_unchanged_after_revocation(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        revocation = RevocationRecord(
            revocation_id="rvk-00000001",
            grant_id="grant-00000001",
            owner_id=OWNER_A,
            revoked_by="owner-piyush-01",
            effective_at=T0 + timedelta(days=2),
            recorded_at=T0 + timedelta(days=2),
            reason="Revoked for test.",
        )
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        assert repo.get_capability_grant(owner_id=OWNER_A, grant_id="grant-00000001") == _grant()
        assert repo.list_revocations_for_grant(owner_id=OWNER_A, grant_id="grant-00000001") == (
            revocation,
        )


# --- causality ---------------------------------------------------------------


def test_orphaned_decision_is_rejected(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        with pytest.raises(AuthorityCausalityError):
            repo.append_approval_decision(_decision(), idempotency_key="k-dec")


def test_grant_from_rejected_decision_is_rejected(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(), idempotency_key="k-req")
        repo.append_approval_decision(
            _decision(outcome=ApprovalDecisionOutcome.REJECTED), idempotency_key="k-dec"
        )
        with pytest.raises(AuthorityCausalityError):
            repo.append_capability_grant(_grant(), idempotency_key="k-grant")


@pytest.mark.parametrize(
    "field,value",
    [
        ("capability", "repository_write"),
        ("purpose", "A different purpose entirely."),
        ("policy_version", "authority-policy-v2"),
    ],
)
def test_grant_must_match_the_approved_decision(database: Database, field: str, value: str) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(), idempotency_key="k-req")
        repo.append_approval_decision(_decision(), idempotency_key="k-dec")
        with pytest.raises(AuthorityCausalityError):
            repo.append_capability_grant(_grant(**{field: value}), idempotency_key="k-grant")


def test_orphaned_revocation_and_evaluation_are_rejected(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        stray_revocation = RevocationRecord(
            revocation_id="rvk-00000001",
            grant_id="grant-00000001",
            owner_id=OWNER_A,
            revoked_by="owner-piyush-01",
            effective_at=T0,
            recorded_at=T0,
            reason="No such grant.",
        )
        with pytest.raises(AuthorityCausalityError):
            repo.append_revocation(stray_revocation, idempotency_key="k-rvk")
        request = _evaluation()
        with pytest.raises(AuthorityCausalityError):
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key="k-eval"
            )


def test_evaluation_record_must_be_the_deterministic_result(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        request = _evaluation()
        forged = evaluate_authority(request).model_copy(
            update={
                "authorized": False,
                "reason_code": AuthorityReasonCode.EXPIRED,
                "detail": "The grant is expired at the evaluation time.",
            }
        )
        with pytest.raises(AuthorityCausalityError):
            repo.append_evaluation_record(request, forged, idempotency_key="k-eval")


def test_effective_persisted_revocation_cannot_be_omitted(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        omitted = _evaluation()
        assert evaluate_authority(omitted).authorized is True
        with pytest.raises(AuthorityCausalityError, match="persisted truth"):
            repo.append_evaluation_record(
                omitted, evaluate_authority(omitted), idempotency_key="k-eval"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id) == ()


def test_complete_effective_revocation_persists_denied_evidence(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        request = _evaluation(revocations=(revocation,))
        decision = evaluate_authority(request)
        stored = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        assert stored.reason_code is AuthorityReasonCode.REVOKED
        row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
        assert row is not None
        assert row.relevant_revocation_id == revocation.revocation_id


def test_earliest_effective_persisted_revocation_controls(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        earliest = _revocation("rvk-00000001", effective_at=T0 + timedelta(hours=1))
        later = _revocation("rvk-00000002", effective_at=T0 + timedelta(hours=2))
        repo.append_revocation(later, idempotency_key="k-rvk-later")
        repo.append_revocation(earliest, idempotency_key="k-rvk-earliest")
        request = _evaluation(revocations=(later, earliest))
        decision = evaluate_authority(request)
        repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
        assert row is not None
        assert row.reason_code == AuthorityReasonCode.REVOKED.value
        assert row.relevant_revocation_id == earliest.revocation_id


def test_future_persisted_revocation_is_nonblocking_but_must_be_present(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        future = _revocation("rvk-00000001", effective_at=T0 + timedelta(days=2))
        repo.append_revocation(future, idempotency_key="k-rvk")
        request = _evaluation(revocations=(future,))
        decision = evaluate_authority(request)
        stored = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        assert stored.authorized is True
        row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
        assert row is not None
        assert row.relevant_revocation_id is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (
            "subject",
            SubjectReference(subject_type=SubjectType.AGENT, subject_id="agent-other-0002"),
        ),
        ("capability", "repository_write"),
        (
            "scope",
            AuthorityScope(
                resource_type="repository",
                resource_id="orbitmind-other",
                constraints=(ScopeConstraint(name="ref", value="rev-other"),),
            ),
        ),
        ("purpose", "A substituted purpose."),
        ("policy_version", "authority-policy-v2"),
    ],
)
def test_same_owner_same_id_substituted_grant_is_rejected(
    database: Database, field: str, value: object
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        substituted_grant = _grant().model_copy(update={field: value})
        request = _evaluation(grant=substituted_grant)
        with pytest.raises(AuthorityCausalityError, match="persisted truth"):
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key=f"k-eval-{field}"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=substituted_grant.grant_id) == ()


def test_same_owner_same_id_substituted_decision_is_rejected(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        substituted_decision = _decision().model_copy(
            update={"outcome": ApprovalDecisionOutcome.REJECTED}
        )
        request = _evaluation(approval_decision=substituted_decision)
        with pytest.raises(AuthorityCausalityError, match="persisted truth"):
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key="k-eval-decision"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id="grant-00000001") == ()


def test_rejected_persisted_decision_cannot_be_replaced_by_supplied_approval(
    database: Database,
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        rejected = _decision().model_copy(update={"outcome": ApprovalDecisionOutcome.REJECTED})
        canonical = canonical_authority_json(rejected)
        row = session.get(AuthorityApprovalDecisionRow, (rejected.decision_id, OWNER_A))
        assert row is not None
        row.outcome = rejected.outcome.value
        row.canonical_payload = json.loads(canonical)
        row.record_identity = _identity(_DECISION_IDENTITY, canonical)
        request = _evaluation()
        with pytest.raises(AuthorityCausalityError, match="persisted truth"):
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key="k-eval-rejected"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id="grant-00000001") == ()


def test_substituted_relevant_revocation_cannot_replace_stored_revocation(
    database: Database,
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        stored_revocation = _revocation("rvk-00000001")
        repo.append_revocation(stored_revocation, idempotency_key="k-rvk")
        substituted = _revocation("rvk-00000002")
        request = _evaluation(revocations=(substituted,))
        with pytest.raises(AuthorityCausalityError, match="persisted truth"):
            repo.append_evaluation_record(
                request, evaluate_authority(request), idempotency_key="k-eval-wrong-revocation"
            )
        assert repo.list_evaluations(owner_id=OWNER_A, grant_id=stored_revocation.grant_id) == ()


def test_complete_stored_chain_replay_is_idempotent(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        request = _evaluation(revocations=(revocation,))
        decision = evaluate_authority(request)
        first = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        second = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        assert first == second
        assert len(repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id)) == 1


def test_rejected_chain_validation_leaves_the_transaction_usable(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        omitted = _evaluation()
        with pytest.raises(AuthorityCausalityError, match="persisted truth"):
            repo.append_evaluation_record(
                omitted, evaluate_authority(omitted), idempotency_key="k-bad"
            )
        complete = _evaluation(evaluation_id="eval-0000002", revocations=(revocation,))
        stored = repo.append_evaluation_record(
            complete, evaluate_authority(complete), idempotency_key="k-good"
        )
        assert stored.reason_code is AuthorityReasonCode.REVOKED
        assert len(repo.list_evaluations(owner_id=OWNER_A, grant_id=revocation.grant_id)) == 1


def test_revocation_and_evaluation_append_lock_the_same_owner_grant(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        observed: list[tuple[str, str]] = []
        original_lock = repo._lock_owner_grant_for_authority_append

        def record_lock(owner_id: str, grant_id: str) -> CapabilityGrant:
            observed.append((owner_id, grant_id))
            return original_lock(owner_id, grant_id)  # type: ignore[return-value]

        monkeypatch.setattr(repo, "_lock_owner_grant_for_authority_append", record_lock)
        revocation = _revocation()
        repo.append_revocation(revocation, idempotency_key="k-rvk")
        request = _evaluation(revocations=(revocation,))
        repo.append_evaluation_record(
            request, evaluate_authority(request), idempotency_key="k-eval"
        )
        assert observed == [(OWNER_A, revocation.grant_id), (OWNER_A, revocation.grant_id)]


def test_grant_lock_helper_is_owner_scoped_and_non_disclosing(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        with pytest.raises(AuthorityCausalityError, match="missing grant"):
            repo._lock_owner_grant_for_authority_append(OWNER_A, "grant-00000009")
        with pytest.raises(AuthorityCausalityError, match="missing grant"):
            repo._lock_owner_grant_for_authority_append(OWNER_B, "grant-00000001")


def test_evaluation_resolves_stored_chain_after_grant_lock(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        events: list[str] = []
        original_lock = repo._lock_owner_grant_for_authority_append
        original_request = repo._authoritative_evaluation_request

        def record_lock(owner_id: str, grant_id: str) -> object:
            events.append("lock")
            return original_lock(owner_id, grant_id)

        def record_resolution(
            request: AuthorityEvaluationRequest, locked_grant_row: object
        ) -> AuthorityEvaluationRequest:
            events.append("resolve")
            return original_request(request, locked_grant_row)  # type: ignore[arg-type]

        monkeypatch.setattr(repo, "_lock_owner_grant_for_authority_append", record_lock)
        monkeypatch.setattr(repo, "_authoritative_evaluation_request", record_resolution)
        request = _evaluation()
        repo.append_evaluation_record(
            request, evaluate_authority(request), idempotency_key="k-eval"
        )
        assert events == ["lock", "resolve"]


def test_revocation_inserts_only_after_grant_lock(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        events: list[str] = []
        original_lock = repo._lock_owner_grant_for_authority_append
        original_insert = repo._insert

        def record_lock(owner_id: str, grant_id: str) -> object:
            events.append("lock")
            return original_lock(owner_id, grant_id)

        def record_insert(*args: object, **kwargs: object) -> object:
            events.append("insert")
            return original_insert(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(repo, "_lock_owner_grant_for_authority_append", record_lock)
        monkeypatch.setattr(repo, "_insert", record_insert)
        repo.append_revocation(_revocation(), idempotency_key="k-rvk")
        assert events == ["lock", "insert"]


def test_revocation_replay_is_idempotent_with_grant_lock(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        revocation = _revocation()
        first = repo.append_revocation(revocation, idempotency_key="k-rvk")
        second = repo.append_revocation(revocation, idempotency_key="k-rvk")
        assert first == second == revocation


# --- idempotency / replay ----------------------------------------------------


def test_identical_replay_returns_the_same_truth(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        first = repo.append_approval_request(_request(), idempotency_key="k")
        second = repo.append_approval_request(_request(), idempotency_key="k")
        assert first == second == _request()
        assert repo.list_approval_requests(owner_id=OWNER_A) == (_request(),)


def test_conflicting_replay_fails_closed(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        repo.append_approval_request(_request(), idempotency_key="k")
        with pytest.raises(IdempotencyConflictError):
            repo.append_approval_request(
                _request(purpose="A different purpose entirely."), idempotency_key="k"
            )
        # Original truth is unchanged.
        assert repo.get_approval_request(owner_id=OWNER_A, request_id="req-00000001") == _request()


def test_evaluation_replay_is_idempotent_and_conflict_fails(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAuthorityRepository(session)
        _seed_chain(repo)
        request = _evaluation()
        decision = evaluate_authority(request)
        first = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        second = repo.append_evaluation_record(request, decision, idempotency_key="k-eval")
        assert first == second
        other = _evaluation(evaluation_time=T0 + timedelta(days=2))
        with pytest.raises(IdempotencyConflictError):
            repo.append_evaluation_record(
                other, evaluate_authority(other), idempotency_key="k-eval"
            )


# --- transactions / rollback -------------------------------------------------


def test_failed_append_rolls_back_and_preserves_prior_truth(database: Database) -> None:
    with database.session() as session:
        repo = SqlAlchemyAuthorityRepository(session)
        with session.begin():
            repo.append_approval_request(_request(), idempotency_key="k-req")
        with pytest.raises(AuthorityCausalityError), session.begin():
            # A valid request insert followed by an orphaned grant in one tx.
            repo.append_approval_request(
                _request(request_id="req-00000002"), idempotency_key="k-req-2"
            )
            repo.append_capability_grant(_grant(), idempotency_key="k-grant")
    with database.session() as session:
        repo = SqlAlchemyAuthorityRepository(session)
        # The orphaned-grant transaction rolled back entirely: req-2 is absent.
        assert repo.get_approval_request(owner_id=OWNER_A, request_id="req-00000002") is None
        assert repo.get_approval_request(owner_id=OWNER_A, request_id="req-00000001") is not None
        assert repo.list_capability_grants(owner_id=OWNER_A) == ()


# --- fail-closed reads -------------------------------------------------------


def _persist_evaluation(repo: SqlAlchemyAuthorityRepository) -> AuthorityEvaluationRequest:
    _seed_chain(repo)
    request = _evaluation()
    repo.append_evaluation_record(request, evaluate_authority(request), idempotency_key="k-eval")
    return request


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("allowed", False),
        ("reason_code", AuthorityReasonCode.REVOKED.value),
        ("relevant_revocation_id", "rvk-00000001"),
        ("evaluation_time", T0 + timedelta(days=2)),
        ("grant_id", "grant-00000009"),
        ("request_id", "req-00000009"),
        ("decision_id", "dec-00000009"),
        ("capability", "repository_write"),
        ("policy_version", "authority-policy-v2"),
    ],
)
def test_tampered_evaluation_scalar_projection_fails_closed(
    database: Database, field: str, value: object
) -> None:
    with database.session() as session:
        with session.begin():
            request = _persist_evaluation(SqlAlchemyAuthorityRepository(session))
        with session.begin():
            row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
            assert row is not None
            setattr(row, field, value)
        repo = SqlAlchemyAuthorityRepository(session)
        with pytest.raises(AuthorityRecordCorruptError, match="projection mismatch"):
            repo.list_evaluations(owner_id=OWNER_A, grant_id="grant-00000001")


@pytest.mark.parametrize("payload_field", ["subject", "scope", "purpose"])
def test_tampered_evaluation_request_semantics_fail_closed(
    database: Database, payload_field: str
) -> None:
    with database.session() as session:
        with session.begin():
            request = _persist_evaluation(SqlAlchemyAuthorityRepository(session))
        with session.begin():
            row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
            assert row is not None
            payload = json.loads(json.dumps(row.request_payload))
            if payload_field == "subject":
                payload["subject"]["subject_id"] = "agent-other-0002"
            elif payload_field == "scope":
                payload["scope"]["resource_id"] = "orbitmind-other"
            else:
                payload["purpose"] = "A tampered purpose."
            row.request_payload = payload
        repo = SqlAlchemyAuthorityRepository(session)
        with pytest.raises(AuthorityRecordCorruptError, match="identity mismatch"):
            repo.list_evaluations(owner_id=OWNER_A, grant_id="grant-00000001")


def test_corrupt_evaluation_in_list_fails_the_entire_read(database: Database) -> None:
    with database.session() as session:
        with session.begin():
            repo = SqlAlchemyAuthorityRepository(session)
            _seed_chain(repo)
            first = _evaluation()
            second = _evaluation(evaluation_id="eval-0000002")
            repo.append_evaluation_record(
                first, evaluate_authority(first), idempotency_key="k-eval-1"
            )
            repo.append_evaluation_record(
                second, evaluate_authority(second), idempotency_key="k-eval-2"
            )
        with session.begin():
            row = session.get(AuthorityEvaluationRow, (first.evaluation_id, OWNER_A))
            assert row is not None
            row.allowed = False
        with pytest.raises(AuthorityRecordCorruptError, match="projection mismatch"):
            SqlAlchemyAuthorityRepository(session).list_evaluations(
                owner_id=OWNER_A, grant_id="grant-00000001"
            )


def test_tampered_evaluation_record_identity_fails_closed(database: Database) -> None:
    with database.session() as session:
        with session.begin():
            request = _persist_evaluation(SqlAlchemyAuthorityRepository(session))
        with session.begin():
            row = session.get(AuthorityEvaluationRow, (request.evaluation_id, OWNER_A))
            assert row is not None
            row.record_identity = "0" * 64
        with pytest.raises(AuthorityRecordCorruptError, match="identity mismatch"):
            SqlAlchemyAuthorityRepository(session).list_evaluations(
                owner_id=OWNER_A, grant_id="grant-00000001"
            )


def test_tampered_stored_payload_fails_closed_on_read(database: Database) -> None:
    from orbitmind.persistence.authority_models import AuthorityApprovalRequestRow

    with database.session() as session:
        with session.begin():
            repo = SqlAlchemyAuthorityRepository(session)
            repo.append_approval_request(_request(), idempotency_key="k-req")
        with session.begin():
            row = session.get(AuthorityApprovalRequestRow, ("req-00000001", OWNER_A))
            assert row is not None
            tampered = dict(row.canonical_payload)
            tampered["purpose"] = "Silently widened purpose."
            row.canonical_payload = tampered
        repo = SqlAlchemyAuthorityRepository(session)
        with pytest.raises(AuthorityRecordCorruptError):
            repo.get_approval_request(owner_id=OWNER_A, request_id="req-00000001")


def test_unknown_stored_enum_fails_closed_on_read(database: Database) -> None:
    from orbitmind.persistence.authority_models import AuthorityApprovalDecisionRow

    with database.session() as session:
        with session.begin():
            repo = SqlAlchemyAuthorityRepository(session)
            repo.append_approval_request(_request(), idempotency_key="k-req")
            repo.append_approval_decision(_decision(), idempotency_key="k-dec")
        with session.begin():
            row = session.get(AuthorityApprovalDecisionRow, ("dec-00000001", OWNER_A))
            assert row is not None
            tampered = dict(row.canonical_payload)
            tampered["outcome"] = "coerced"
            row.canonical_payload = tampered
        repo = SqlAlchemyAuthorityRepository(session)
        with pytest.raises(AuthorityRecordCorruptError):
            repo.get_approval_decision(owner_id=OWNER_A, decision_id="dec-00000001")


# --- architecture boundary ---------------------------------------------------


def test_pure_authority_domain_does_not_import_persistence() -> None:
    authority_root = Path(orbitmind.authority.__file__).resolve().parent
    for py_file in authority_root.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("orbitmind.persistence"), py_file.name
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("orbitmind.persistence"), py_file.name


def test_authority_persistence_has_no_api_ui_or_runtime_imports() -> None:
    persistence_root = Path("src/orbitmind/persistence")
    for name in ("authority_models.py", "authority_repository.py"):
        tree = ast.parse((persistence_root / name).read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
        for forbidden in (
            "orbitmind.api",
            "orbitmind.runtime",
            "orbitmind.camera",
            "orbitmind.quantum",
            "orbitmind.laboratory",
            "subprocess",
            "socket",
            "httpx",
        ):
            assert not any(
                module == forbidden or module.startswith(forbidden + ".") for module in modules
            ), f"{name} imports {forbidden}"
