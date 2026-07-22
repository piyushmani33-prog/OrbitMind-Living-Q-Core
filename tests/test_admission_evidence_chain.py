"""Truthful owner-scoped Authority-Admission projection tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from orbitmind.admission.contracts import (
    OPERATION_PROFILES,
    AdmissionOperationKind,
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
from orbitmind.orchestration.admission_evidence import (
    read_admission_evidence_chain,
    read_request_admission_chain,
)
from orbitmind.orchestration.admission_lifecycle import admit_operation
from orbitmind.orchestration.authority_lifecycle import (
    CreateApprovalRequestCommand,
    IssueCapabilityGrantCommand,
    RecordApprovalDecisionCommand,
    create_approval_request,
    issue_capability_grant,
    record_approval_decision,
)
from orbitmind.persistence.database import Database

_T0 = datetime(2026, 7, 22, tzinfo=UTC)
_OWNER = "owner-piyush-01"
_OTHER_OWNER = "owner-second-02"
_ACTOR = "agent-dev-0001"
_POLICY = "authority-policy-v1"
_SCOPE = ProposalScope(resource_type="repository", resource_id="orbitmind-main")
_AUTH_SCOPE = AuthorityScope(resource_type="repository", resource_id="orbitmind-main")


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    database = Database(f"sqlite:///{(tmp_path / 'admission-evidence.db').as_posix()}")
    database.create_all()
    try:
        yield database
    finally:
        database.dispose()


def _seed_grant(database: Database, *, request_id: str, decision_id: str, grant_id: str) -> None:
    with database.session() as session:
        create_approval_request(
            session=session,
            command=CreateApprovalRequestCommand(
                owner_id=_OWNER,
                request_id=request_id,
                requested_by=_OWNER,
                subject=SubjectReference(subject_type=SubjectType.AGENT, subject_id=_ACTOR),
                capability="repository_write_proposal",
                scope=_AUTH_SCOPE,
                purpose="Bounded evidence projection test.",
                policy_version=_POLICY,
                requested_at=_T0 - timedelta(days=2),
                valid_from=_T0 - timedelta(days=1),
                expires_at=_T0 + timedelta(days=1),
                idempotency_key=f"{request_id}-key",
            ),
        )
        record_approval_decision(
            session=session,
            command=RecordApprovalDecisionCommand(
                owner_id=_OWNER,
                decision_id=decision_id,
                request_id=request_id,
                decided_by=OperatorReference(subject_id="operator-piyush-1"),
                outcome=ApprovalDecisionOutcome.APPROVED,
                decided_at=_T0 - timedelta(hours=12),
                reason="Approved for projection tests.",
                policy_version=_POLICY,
                idempotency_key=f"{decision_id}-key",
            ),
        )
        issue_capability_grant(
            session=session,
            command=IssueCapabilityGrantCommand(
                owner_id=_OWNER,
                grant_id=grant_id,
                request_id=request_id,
                decision_id=decision_id,
                issued_by=OperatorReference(subject_id="operator-piyush-1"),
                issued_at=_T0 - timedelta(hours=6),
                valid_from=_T0 - timedelta(days=1),
                expires_at=_T0 + timedelta(days=1),
                policy_version=_POLICY,
                idempotency_key=f"{grant_id}-key",
            ),
        )


def _admit(
    database: Database,
    *,
    proposal_id: str,
    key: str,
    evaluated_at: datetime,
    grant_id: str | None = None,
) -> str:
    kind = (
        AdmissionOperationKind.PROPOSE_FILE_CHANGE
        if grant_id is not None
        else AdmissionOperationKind.READ_REPOSITORY
    )
    profile = OPERATION_PROFILES[kind]
    proposal = OperationProposal(
        proposal_id=proposal_id,
        owner_id=_OWNER,
        actor_id=_ACTOR,
        actor_type=ProposalActorType.AGENT,
        operation_kind=kind.value,
        requested_capability=profile.required_capability,
        requested_scope=_SCOPE,
        side_effect_class=profile.side_effect_class,
        risk_class=profile.risk_class,
        purpose="Bounded evidence projection test.",
        requested_authority_grant_id=grant_id,
        requested_at=_T0,
        idempotency_key=key,
    )
    with database.session() as session:
        return admit_operation(
            session=session,
            proposal=proposal,
            authoritative_owner_id=_OWNER,
            authoritative_actor_id=_ACTOR,
            evaluated_at=evaluated_at,
        ).record.admission_id


def test_admission_centric_null_link_and_cross_owner_are_truthful(database: Database) -> None:
    admission_id = _admit(
        database,
        proposal_id="prop-null-00001",
        key="null-link-key",
        evaluated_at=_T0,
    )
    with database.session() as session:
        chain = read_admission_evidence_chain(
            session=session, owner_id=_OWNER, admission_id=admission_id
        )
    assert chain is not None
    assert chain.admission.admission_id == admission_id
    assert chain.authority is None

    with database.session() as session:
        assert (
            read_admission_evidence_chain(
                session=session, owner_id=_OTHER_OWNER, admission_id=admission_id
            )
            is None
        )


def test_linked_projection_filters_to_the_exact_grant(database: Database) -> None:
    _seed_grant(
        database,
        request_id="req-first-00001",
        decision_id="dec-first-00001",
        grant_id="grant-first-00001",
    )
    admission_id = _admit(
        database,
        proposal_id="prop-link-00001",
        key="linked-key-001",
        evaluated_at=_T0,
        grant_id="grant-first-00001",
    )
    with database.session() as session:
        chain = read_admission_evidence_chain(
            session=session, owner_id=_OWNER, admission_id=admission_id
        )
    assert chain is not None
    assert chain.authority is not None
    assert [grant.grant_id for grant in chain.authority.capability_grants] == ["grant-first-00001"]


def test_request_projection_is_deterministic_bounded_and_grant_linked_only(
    database: Database,
) -> None:
    _seed_grant(
        database,
        request_id="req-first-00001",
        decision_id="dec-first-00001",
        grant_id="grant-first-00001",
    )
    _seed_grant(
        database,
        request_id="req-other-00001",
        decision_id="dec-other-00001",
        grant_id="grant-other-00001",
    )
    expected = [
        _admit(
            database,
            proposal_id=f"prop-link-0000{index}",
            key=f"linked-key-00{index}",
            evaluated_at=_T0 + timedelta(seconds=index),
            grant_id="grant-first-00001",
        )
        for index in (1, 2)
    ]
    _admit(
        database,
        proposal_id="prop-null-00001",
        key="null-link-key",
        evaluated_at=_T0 + timedelta(seconds=3),
    )
    _admit(
        database,
        proposal_id="prop-other-0001",
        key="other-link-key",
        evaluated_at=_T0 + timedelta(seconds=4),
        grant_id="grant-other-00001",
    )

    with database.session() as session:
        first_page = read_request_admission_chain(
            session=session, owner_id=_OWNER, request_id="req-first-00001", limit=1
        )
    assert first_page is not None
    assert [record.admission_id for record in first_page.admissions] == expected[:1]
    assert first_page.page_size == 1
    assert first_page.truncated is True

    with database.session() as session:
        full = read_request_admission_chain(
            session=session, owner_id=_OWNER, request_id="req-first-00001", limit=5
        )
    assert full is not None
    assert [record.admission_id for record in full.admissions] == expected
    assert full.truncated is False

    with database.session() as session:
        assert (
            read_request_admission_chain(
                session=session,
                owner_id=_OTHER_OWNER,
                request_id="req-first-00001",
                limit=5,
            )
            is None
        )
