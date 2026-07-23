"""Real PostgreSQL persistence proofs for U8.1A (disposable database only)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

import orbitmind.orchestration.tool_gateway_lifecycle as gateway_lifecycle
from orbitmind.admission.contracts import (
    AdmissionOutcome,
    AdmissionReasonCode,
    AdmissionRecord,
    AdmissionRiskClass,
    AdmissionSideEffectClass,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.orchestration.tool_gateway_lifecycle import evaluate_tool_invocation
from orbitmind.persistence.admission_models import OperationAdmissionRecordRow
from orbitmind.persistence.admission_repository import SqlAlchemyAdmissionRepository
from orbitmind.persistence.database import Database
from orbitmind.persistence.tool_gateway_models import OperationToolGatewayDecisionRow
from orbitmind.persistence.tool_gateway_repository import (
    GatewayDecisionCorruptError,
    GatewayDisposition,
    SqlAlchemyToolGatewayRepository,
)
from orbitmind.toolgateway.contracts import ToolInvocationProposal

POSTGRES_URL = os.getenv("ORBITMIND_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="set ORBITMIND_TEST_POSTGRES_URL to a disposable PostgreSQL database",
)
T0 = datetime(2026, 7, 22, tzinfo=UTC)
OWNER = "owner-pg-gateway-01"
OWNER_B = "owner-pg-gateway-02"
ACTOR = "actor-pg-gateway-01"


@pytest.fixture
def database() -> Iterator[Database]:
    assert POSTGRES_URL is not None
    db = Database(POSTGRES_URL)
    db.create_all()
    with db.session() as session, session.begin():
        session.execute(delete(OperationToolGatewayDecisionRow))
        session.execute(delete(OperationAdmissionRecordRow))
    try:
        yield db
    finally:
        with db.session() as session, session.begin():
            session.execute(delete(OperationToolGatewayDecisionRow))
            session.execute(delete(OperationAdmissionRecordRow))
        db.dispose()


def _admission(admission_id: str = "admission-pg-0001") -> AdmissionRecord:
    return AdmissionRecord(
        admission_id=admission_id,
        owner_id=OWNER,
        proposal_id="proposal-pg-admission-0001",
        actor_id=ACTOR,
        actor_type=ProposalActorType.AGENT,
        operation_kind="read_repository",
        requested_capability="repository_read",
        requested_scope=ProposalScope(resource_type="repository", resource_id="orbitmind-main"),
        side_effect_class=AdmissionSideEffectClass.LOCAL_READ,
        risk_class=AdmissionRiskClass.LOW,
        outcome=AdmissionOutcome.ADMITTED,
        primary_reason_code=AdmissionReasonCode.ADMITTED_BY_POLICY,
        reason_codes=(AdmissionReasonCode.ADMITTED_BY_POLICY,),
        evaluated_at=T0,
        requested_at=T0,
        proposal_fingerprint="a" * 64,
        decision_checksum="b" * 64,
        created_at=T0,
        provenance_refs=(),
    )


def _seed(database: Database, admission_id: str = "admission-pg-0001") -> str:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        stored = repo.append_admission_record(
            _admission(admission_id), idempotency_key=f"key-{admission_id}"
        )
    with database.session() as session, session.begin():
        verified = SqlAlchemyAdmissionRepository(session).get_verified_admission_record(
            owner_id=OWNER, admission_id=stored.record.admission_id
        )
    assert verified is not None
    return verified.record_identity


def _proposal(
    admission_id: str = "admission-pg-0001",
    *,
    proposal_id: str = "proposal-pg-gateway-0001",
    key: str = "gateway-pg-key-0001",
) -> ToolInvocationProposal:
    return ToolInvocationProposal(
        proposal_id=proposal_id,
        owner_id=OWNER,
        actor_id=ACTOR,
        admission_id=admission_id,
        tool_id="repository_file_reader",
        tool_version="1.0.0",
        input_schema_reference="repository_read_request",
        purpose="PostgreSQL gateway persistence proof.",
        requested_at=T0,
        idempotency_key=key,
    )


def _evaluate(database: Database, proposal: ToolInvocationProposal) -> Any:
    with database.session() as session:
        return evaluate_tool_invocation(
            session=session,
            proposal=proposal,
            authoritative_owner_id=OWNER,
            authoritative_actor_id=ACTOR,
            evaluated_at=T0,
        )


def test_postgres_cross_session_restart_replay_identity_and_owner_isolation(
    database: Database,
) -> None:
    identity = _seed(database)
    proposal = _proposal()
    created = _evaluate(database, proposal)
    assert created.disposition is GatewayDisposition.CREATED
    assert created.record.admission_record_identity == identity

    assert POSTGRES_URL is not None
    restarted = Database(POSTGRES_URL)
    try:
        replayed = _evaluate(restarted, proposal)
        assert replayed.disposition is GatewayDisposition.REPLAYED
        assert replayed.record == created.record
        with restarted.session() as session, session.begin():
            repo = SqlAlchemyToolGatewayRepository(session)
            assert (
                repo.get_gateway_decision_record(
                    owner_id=OWNER_B,
                    gateway_decision_id=created.record.gateway_decision_id,
                )
                is None
            )
            assert len(repo.list_gateway_decision_records_bounded(owner_id=OWNER, limit=10)) == 1
    finally:
        restarted.dispose()


def test_postgres_resolved_admission_fk_is_restrict(database: Database) -> None:
    _seed(database)
    _evaluate(database, _proposal())
    with database.session() as session, pytest.raises(IntegrityError), session.begin():
        session.execute(
            delete(OperationAdmissionRecordRow).where(
                OperationAdmissionRecordRow.owner_id == OWNER,
                OperationAdmissionRecordRow.admission_id == "admission-pg-0001",
            )
        )


def test_postgres_tamper_fails_closed(database: Database) -> None:
    _seed(database)
    result = _evaluate(database, _proposal())
    with database.session() as session, session.begin():
        row = session.get(
            OperationToolGatewayDecisionRow,
            (result.record.gateway_decision_id, OWNER),
        )
        assert row is not None
        row.record_identity = "f" * 64
    with (
        database.session() as session,
        session.begin(),
        pytest.raises(GatewayDecisionCorruptError),
    ):
        SqlAlchemyToolGatewayRepository(session).get_gateway_decision_record(
            owner_id=OWNER,
            gateway_decision_id=result.record.gateway_decision_id,
        )


def test_postgres_synchronized_first_write_race(database: Database) -> None:
    _seed(database, "admission-pg-race-0001")
    proposal = _proposal(
        "admission-pg-race-0001",
        proposal_id="proposal-pg-race-0001",
        key="gateway-pg-race-key-0001",
    )
    barrier = Barrier(2)
    original = gateway_lifecycle.evaluate_gateway_proposal

    def synchronized(*args: Any, **kwargs: Any) -> Any:
        decision = original(*args, **kwargs)
        barrier.wait(timeout=15)
        return decision

    with (
        patch.object(gateway_lifecycle, "evaluate_gateway_proposal", side_effect=synchronized),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        results = tuple(pool.map(lambda _index: _evaluate(database, proposal), range(2)))

    assert {result.disposition for result in results} == {
        GatewayDisposition.CREATED,
        GatewayDisposition.REPLAYED,
    }
    assert results[0].record == results[1].record
    with database.session() as session:
        count = session.scalar(
            select(func.count())
            .select_from(OperationToolGatewayDecisionRow)
            .where(
                OperationToolGatewayDecisionRow.owner_id == OWNER,
                OperationToolGatewayDecisionRow.idempotency_key == "gateway-pg-race-key-0001",
            )
        )
    assert count == 1
