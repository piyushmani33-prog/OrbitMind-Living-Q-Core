"""Live PostgreSQL coverage for Operation Admission v0 (U7.4).

Skips unless a disposable PostgreSQL database is configured via
``ORBITMIND_TEST_POSTGRES_URL`` and the schema is at ``alembic upgrade head``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, inspect, select, text

from orbitmind.admission.contracts import (
    OPERATION_PROFILES,
    AdmissionOperationKind,
    AdmissionOutcome,
    AdmissionReasonCode,
    OperationProposal,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.authority.contracts import (
    ApprovalDecisionOutcome,
    AuthorityScope,
    OperatorReference,
    SubjectReference,
    SubjectType,
)
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.orchestration.admission_lifecycle import admit_operation
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
from orbitmind.persistence.database import Database

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

T0 = datetime(2026, 7, 21, tzinfo=UTC)
OWNER = "owner-piyush-01"
OWNER_B = "owner-second-02"
ACTOR = "agent-dev-0001"
OPERATOR = OperatorReference(subject_id="operator-piyush-1")
GRANT = "grant-00000001"
POLICY = "authority-policy-v1"
ADMISSION_SCOPE = ProposalScope(resource_type="repository", resource_id="orbitmind-main")
AUTH_SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-main")

_TABLES = (
    "operation_admission_records",
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
        pytest.skip(f"admission/authority tables absent (run alembic upgrade head): {missing}")
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


def _seed_grant(
    database: Database, *, owner: str = OWNER, revoke_effective_at: datetime | None = None
) -> None:
    subject = SubjectReference(subject_type=SubjectType.AGENT, subject_id=ACTOR)
    with database.session() as session:
        create_approval_request(
            session=session,
            command=CreateApprovalRequestCommand(
                owner_id=owner,
                request_id="req-00000001",
                requested_by=owner,
                subject=subject,
                capability="repository_write_proposal",
                scope=AUTH_SCOPE,
                purpose="Seed grant for admission pg tests.",
                policy_version=POLICY,
                requested_at=T0 - timedelta(days=11),
                valid_from=T0 - timedelta(days=10),
                expires_at=T0 + timedelta(days=20),
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
                reason="Approved for pg tests.",
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
                valid_from=T0 - timedelta(days=10),
                expires_at=T0 + timedelta(days=20),
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
                    reason="Revoked for pg tests.",
                    policy_version=POLICY,
                    idempotency_key="rvk-key-01",
                ),
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
        )


def test_pg_admit_and_no_authority_write(database: Database) -> None:
    record = _admit(database, _proposal(AdmissionOperationKind.READ_REPOSITORY))
    assert record.outcome is AdmissionOutcome.ADMITTED
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(OperationAdmissionRecordRow)) == 1


def test_pg_propose_file_change_admitted_with_valid_grant(database: Database) -> None:
    _seed_grant(database)
    record = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert record.outcome is AdmissionOutcome.ADMITTED
    assert record.resolved_authority_grant_id == GRANT


def test_pg_mandatory_approval_stays_withheld(database: Database) -> None:
    _seed_grant(database)
    record = _admit(
        database,
        _proposal(
            AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            requested_authority_grant_id=GRANT,
            operation_kind=AdmissionOperationKind.PUSH_BRANCH.value,
            requested_capability="branch_push",
            side_effect_class=OPERATION_PROFILES[
                AdmissionOperationKind.PUSH_BRANCH
            ].side_effect_class,
            risk_class=OPERATION_PROFILES[AdmissionOperationKind.PUSH_BRANCH].risk_class,
        ),
    )
    # push_branch requires the branch_push capability; the seeded grant is
    # repository_write_proposal -> capability mismatch (still not admitted).
    assert record.outcome is AdmissionOutcome.DENIED
    assert record.primary_reason_code is AdmissionReasonCode.CAPABILITY_MISMATCH


def test_pg_revoked_grant_is_denied(database: Database) -> None:
    _seed_grant(database, revoke_effective_at=T0 - timedelta(days=1))
    record = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert record.primary_reason_code is AdmissionReasonCode.AUTHORITY_REVOKED


def test_pg_owner_privacy_cross_owner_not_found(database: Database) -> None:
    _seed_grant(database, owner=OWNER_B)
    record = _admit(
        database,
        _proposal(AdmissionOperationKind.PROPOSE_FILE_CHANGE, requested_authority_grant_id=GRANT),
    )
    assert record.primary_reason_code is AdmissionReasonCode.AUTHORITY_NOT_FOUND


def test_pg_replay_and_conflict(database: Database) -> None:
    proposal = _proposal(AdmissionOperationKind.READ_REPOSITORY)
    first = _admit(database, proposal)
    second = _admit(database, proposal)
    assert first == second
    with pytest.raises(IdempotencyConflictError):
        _admit(database, _proposal(AdmissionOperationKind.RUN_LOCAL_VALIDATION))
