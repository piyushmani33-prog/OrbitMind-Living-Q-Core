"""End-to-end Operation Admission v0 service coverage (offline SQLite).

Exercises ``admit_operation``: the authority bridge, deterministic outcomes,
immutable persistence, replay, mandatory-approval withholding, owner privacy,
trusted-clock time semantics, and the absence of any execution or authority write.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

import orbitmind.orchestration.admission_lifecycle as admission_lifecycle
from orbitmind.admission.contracts import (
    AdmissionOperationKind,
    AdmissionOutcome,
    AdmissionReasonCode,
    OperationProposal,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.admission.contracts import (
    ScopeConstraint as AdmissionScopeConstraint,
)
from orbitmind.authority.contracts import (
    ApprovalDecisionOutcome,
    AuthorityScope,
    OperatorReference,
    SubjectReference,
    SubjectType,
)
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.orchestration.admission_lifecycle import AdmissionDisposition, admit_operation
from orbitmind.orchestration.authority_lifecycle import (
    CreateApprovalRequestCommand,
    IssueCapabilityGrantCommand,
    RecordApprovalDecisionCommand,
    RevokeCapabilityGrantCommand,
    create_approval_request,
    issue_capability_grant,
    record_approval_decision,
    revoke_capability_grant,
)
from orbitmind.persistence.admission_models import OperationAdmissionRecordRow
from orbitmind.persistence.authority_models import AuthorityEvaluationRow
from orbitmind.persistence.database import Database

T0 = datetime(2026, 7, 21, tzinfo=UTC)
OWNER = "owner-piyush-01"
OWNER_B = "owner-second-02"
ACTOR = "agent-dev-0001"
OPERATOR = OperatorReference(subject_id="operator-piyush-1")
GRANT = "grant-00000001"
POLICY = "authority-policy-v1"
ADMISSION_SCOPE = ProposalScope(resource_type="repository", resource_id="orbitmind-main")
AUTH_SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-main")


@pytest.fixture
def database(tmp_path: Any) -> Iterator[Database]:
    db = Database(f"sqlite:///{tmp_path / 'admission-services.db'}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _seed_grant(
    database: Database,
    *,
    owner: str = OWNER,
    subject_id: str = ACTOR,
    capability: str = "repository_write_proposal",
    scope: AuthorityScope = AUTH_SCOPE,
    valid_from: datetime = T0 - timedelta(days=10),
    expires_at: datetime = T0 + timedelta(days=20),
    revoke_effective_at: datetime | None = None,
) -> None:
    subject = SubjectReference(subject_type=SubjectType.AGENT, subject_id=subject_id)
    with database.session() as session:
        create_approval_request(
            session=session,
            command=CreateApprovalRequestCommand(
                owner_id=owner,
                request_id="req-00000001",
                requested_by=owner,
                subject=subject,
                capability=capability,
                scope=scope,
                purpose="Seed grant for admission tests.",
                policy_version=POLICY,
                requested_at=T0 - timedelta(days=11),
                valid_from=valid_from,
                expires_at=expires_at,
                idempotency_key="req-key-01",
            ),
        )
        record_approval_decision(
            session=session,
            command=RecordApprovalDecisionCommand(
                owner_id=owner,
                decision_id="dec-00000001",
                request_id="req-00000001",
                decided_by=OPERATOR,
                outcome=ApprovalDecisionOutcome.APPROVED,
                decided_at=T0 - timedelta(days=10, hours=12),
                reason="Approved for tests.",
                policy_version=POLICY,
                idempotency_key="dec-key-01",
            ),
        )
        issue_capability_grant(
            session=session,
            command=IssueCapabilityGrantCommand(
                owner_id=owner,
                grant_id=GRANT,
                request_id="req-00000001",
                decision_id="dec-00000001",
                issued_by=OPERATOR,
                issued_at=T0 - timedelta(days=10, hours=6),
                valid_from=valid_from,
                expires_at=expires_at,
                policy_version=POLICY,
                idempotency_key="grant-key-01",
            ),
        )
        if revoke_effective_at is not None:
            revoke_capability_grant(
                session=session,
                command=RevokeCapabilityGrantCommand(
                    owner_id=owner,
                    revocation_id="rvk-00000001",
                    grant_id=GRANT,
                    revoked_by=owner,
                    effective_at=revoke_effective_at,
                    recorded_at=revoke_effective_at,
                    reason="Revoked for tests.",
                    policy_version=POLICY,
                    idempotency_key="rvk-key-01",
                ),
            )


def _proposal(kind: AdmissionOperationKind, **overrides: Any) -> OperationProposal:
    from orbitmind.admission.contracts import OPERATION_PROFILES

    profile = OPERATION_PROFILES[kind]
    values: dict[str, Any] = {
        "proposal_id": "prop-00000001",
        "owner_id": OWNER,
        "actor_id": ACTOR,
        "actor_type": ProposalActorType.AGENT,
        "operation_kind": kind.value,
        "requested_capability": profile.required_capability,
        "requested_scope": ADMISSION_SCOPE,
        "side_effect_class": profile.side_effect_class,
        "risk_class": profile.risk_class,
        "purpose": "Bounded operation for review evidence.",
        "requested_at": T0,
        "idempotency_key": "adm-key-0001",
    }
    values.update(overrides)
    return OperationProposal(**values)


def _admit(database: Database, proposal: OperationProposal, *, evaluated_at: datetime = T0) -> Any:
    with database.session() as session:
        return admit_operation(
            session=session,
            proposal=proposal,
            authoritative_owner_id=OWNER,
            authoritative_actor_id=ACTOR,
            evaluated_at=evaluated_at,
        ).record


def _admit_result(
    database: Database, proposal: OperationProposal, *, evaluated_at: datetime = T0
) -> Any:
    with database.session() as session:
        return admit_operation(
            session=session,
            proposal=proposal,
            authoritative_owner_id=OWNER,
            authoritative_actor_id=ACTOR,
            evaluated_at=evaluated_at,
        )


def test_read_repository_is_admitted_and_persisted_without_execution(database: Database) -> None:
    record = _admit(database, _proposal(AdmissionOperationKind.READ_REPOSITORY))
    assert record.outcome is AdmissionOutcome.ADMITTED
    assert record.primary_reason_code is AdmissionReasonCode.ADMITTED_BY_POLICY
    assert record.created_at == T0  # created_at == the single injected evaluated_at
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(OperationAdmissionRecordRow)) == 1
        # Admission never writes authority evidence (no execution, no evaluation append).
        assert session.scalar(select(func.count()).select_from(AuthorityEvaluationRow)) == 0


def test_propose_file_change_admitted_only_with_valid_authority(database: Database) -> None:
    _seed_grant(database)
    admitted = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert admitted.outcome is AdmissionOutcome.ADMITTED
    assert admitted.resolved_authority_grant_id == GRANT
    assert admitted.requested_authority_grant_id == GRANT


def test_propose_file_change_without_grant_is_denied(database: Database) -> None:
    record = _admit(database, _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE))
    assert record.outcome is AdmissionOutcome.DENIED
    assert record.primary_reason_code is AdmissionReasonCode.AUTHORITY_REQUIRED
    assert record.resolved_authority_grant_id is None


def test_mandatory_approval_kind_with_valid_authority_stays_approval_required(
    database: Database,
) -> None:
    _seed_grant(database, capability="dependency_install")
    record = _admit(
        database,
        _proposal(AdmissionOperationKind.INSTALL_DEPENDENCY, requested_authority_grant_id=GRANT),
    )
    assert record.outcome is AdmissionOutcome.APPROVAL_REQUIRED
    assert record.primary_reason_code is AdmissionReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED
    assert record.resolved_authority_grant_id == GRANT


def test_forbidden_kind_is_denied_without_authority_lookup(database: Database) -> None:
    record = _admit(
        database, _proposal(AdmissionOperationKind.DEPLOY, requested_authority_grant_id=GRANT)
    )
    assert record.outcome is AdmissionOutcome.DENIED
    assert record.primary_reason_code is AdmissionReasonCode.FORBIDDEN_OPERATION_KIND
    assert record.resolved_authority_grant_id is None


def test_capability_and_scope_mismatch_are_denied(database: Database) -> None:
    _seed_grant(database, capability="repository_read")  # != profile repository_write_proposal
    cap = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert cap.primary_reason_code is AdmissionReasonCode.CAPABILITY_MISMATCH

    other_scope = ProposalScope(resource_type="repository", resource_id="orbitmind-docs")
    scoped = _admit(
        database,
        _proposal(
            AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            requested_authority_grant_id=GRANT,
            requested_scope=other_scope,
            idempotency_key="adm-key-0002",
        ),
    )
    assert scoped.primary_reason_code in (
        AdmissionReasonCode.CAPABILITY_MISMATCH,
        AdmissionReasonCode.SCOPE_MISMATCH,
    )


def test_actor_mismatch_grant_is_authority_actor_mismatch(database: Database) -> None:
    _seed_grant(database, subject_id="agent-dev-0002")
    record = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert record.primary_reason_code is AdmissionReasonCode.AUTHORITY_ACTOR_MISMATCH


def test_revoked_expired_and_not_yet_valid_use_evaluated_at(database: Database) -> None:
    _seed_grant(database, revoke_effective_at=T0 - timedelta(days=1))
    revoked = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert revoked.primary_reason_code is AdmissionReasonCode.AUTHORITY_REVOKED


def test_expired_grant_is_denied_regardless_of_requested_at(database: Database) -> None:
    _seed_grant(database, valid_from=T0 - timedelta(days=10), expires_at=T0 - timedelta(days=1))
    # requested_at is far in the past (inside validity) but evaluated_at is after expiry:
    # only evaluated_at governs.
    record = _admit(
        database,
        _proposal(
            AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            requested_authority_grant_id=GRANT,
            requested_at=T0 - timedelta(days=5),
        ),
        evaluated_at=T0,
    )
    assert record.primary_reason_code is AdmissionReasonCode.AUTHORITY_EXPIRED


def test_owner_privacy_cross_owner_grant_is_not_found(database: Database) -> None:
    # A valid grant exists, but under a DIFFERENT owner. Admission under OWNER must not
    # reveal its existence: the public-safe result is authority_not_found.
    _seed_grant(database, owner=OWNER_B)
    record = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert record.primary_reason_code is AdmissionReasonCode.AUTHORITY_NOT_FOUND
    assert record.resolved_authority_grant_id is None


def test_sequential_replay_returns_original_without_policy_evaluation(
    database: Database,
) -> None:
    proposal = _proposal(AdmissionOperationKind.READ_REPOSITORY)
    original_evaluator = admission_lifecycle.evaluate_admission
    with patch.object(
        admission_lifecycle, "evaluate_admission", wraps=original_evaluator
    ) as evaluator:
        first = _admit_result(database, proposal)
        assert first.disposition is AdmissionDisposition.CREATED
        assert evaluator.call_count == 1
        evaluator.reset_mock()

        second = _admit_result(database, proposal, evaluated_at=T0 + timedelta(days=1))
        assert second.disposition is AdmissionDisposition.REPLAYED
        assert evaluator.call_count == 0

    assert first.record == second.record
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(OperationAdmissionRecordRow)) == 1


def test_authority_replay_uses_historical_record_but_new_operation_sees_revocation(
    database: Database,
) -> None:
    _seed_grant(database)
    proposal = _proposal(
        AdmissionOperationKind.PROPOSE_FILE_CHANGE,
        requested_authority_grant_id=GRANT,
    )
    first = _admit_result(database, proposal)
    assert first.disposition is AdmissionDisposition.CREATED
    assert first.record.outcome is AdmissionOutcome.ADMITTED
    with database.session() as session:
        original_row = session.get(OperationAdmissionRecordRow, (first.record.admission_id, OWNER))
        assert original_row is not None
        original_identity = original_row.record_identity

    with database.session() as session:
        revoke_capability_grant(
            session=session,
            command=RevokeCapabilityGrantCommand(
                owner_id=OWNER,
                revocation_id="rvk-replay-0001",
                grant_id=GRANT,
                revoked_by=OWNER,
                effective_at=T0 + timedelta(hours=1),
                recorded_at=T0 + timedelta(hours=1),
                reason="Revoked before historical replay.",
                policy_version=POLICY,
                idempotency_key="rvk-replay-key",
            ),
        )

    original_authority_evaluator = admission_lifecycle.evaluate_authority
    original_admission_evaluator = admission_lifecycle.evaluate_admission
    with (
        patch.object(
            admission_lifecycle,
            "evaluate_authority",
            wraps=original_authority_evaluator,
        ) as authority_evaluator,
        patch.object(
            admission_lifecycle,
            "evaluate_admission",
            wraps=original_admission_evaluator,
        ) as admission_evaluator,
    ):
        replay = _admit_result(database, proposal, evaluated_at=T0 + timedelta(days=2))
        assert replay.disposition is AdmissionDisposition.REPLAYED
        assert authority_evaluator.call_count == 0
        assert admission_evaluator.call_count == 0

    assert replay.record == first.record
    assert replay.record.outcome is AdmissionOutcome.ADMITTED
    with database.session() as session:
        historical_row = session.get(
            OperationAdmissionRecordRow, (first.record.admission_id, OWNER)
        )
        assert historical_row is not None
        assert historical_row.record_identity == original_identity
        assert session.scalar(select(func.count()).select_from(OperationAdmissionRecordRow)) == 1

    new_proposal = _proposal(
        AdmissionOperationKind.PROPOSE_FILE_CHANGE,
        proposal_id="prop-after-revoke-01",
        requested_authority_grant_id=GRANT,
        idempotency_key="adm-after-revoke-key",
    )
    with (
        patch.object(
            admission_lifecycle,
            "evaluate_authority",
            wraps=original_authority_evaluator,
        ) as authority_evaluator,
        patch.object(
            admission_lifecycle,
            "evaluate_admission",
            wraps=original_admission_evaluator,
        ) as admission_evaluator,
    ):
        current = _admit_result(database, new_proposal, evaluated_at=T0 + timedelta(days=2))
        assert authority_evaluator.call_count == 1
        assert admission_evaluator.call_count == 1
    assert current.disposition is AdmissionDisposition.CREATED
    assert current.record.outcome is AdmissionOutcome.DENIED
    assert current.record.primary_reason_code is AdmissionReasonCode.AUTHORITY_REVOKED


def test_conflicting_historical_replay_fails_before_evaluation(database: Database) -> None:
    original = _admit_result(database, _proposal(AdmissionOperationKind.READ_REPOSITORY))
    original_authority_evaluator = admission_lifecycle.evaluate_authority
    original_admission_evaluator = admission_lifecycle.evaluate_admission
    with (
        patch.object(
            admission_lifecycle,
            "evaluate_authority",
            wraps=original_authority_evaluator,
        ) as authority_evaluator,
        patch.object(
            admission_lifecycle,
            "evaluate_admission",
            wraps=original_admission_evaluator,
        ) as admission_evaluator,
        pytest.raises(IdempotencyConflictError),
    ):
        _admit_result(
            database,
            _proposal(AdmissionOperationKind.RUN_LOCAL_VALIDATION),  # same idempotency_key
        )
    assert authority_evaluator.call_count == 0
    assert admission_evaluator.call_count == 0
    with database.session() as session:
        rows = session.scalars(select(OperationAdmissionRecordRow)).all()
        assert len(rows) == 1
        assert rows[0].admission_id == original.record.admission_id


def test_denied_admission_is_persisted_as_evidence(database: Database) -> None:
    record = _admit(
        database,
        _proposal(
            AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            requested_scope=ProposalScope(
                resource_type="repository",
                resource_id="orbitmind-main",
                constraints=(AdmissionScopeConstraint(name="ref", value="rev-abc123"),),
            ),
        ),
    )
    assert record.outcome is AdmissionOutcome.DENIED
    with database.session() as session:
        stored = session.scalar(
            select(OperationAdmissionRecordRow).where(OperationAdmissionRecordRow.owner_id == OWNER)
        )
    assert stored is not None
    assert stored.outcome == "denied"
    assert len(stored.record_identity) == 64
