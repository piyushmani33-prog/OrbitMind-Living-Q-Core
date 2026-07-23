"""Lifecycle transaction, replay, identity, and durability proofs for U8.1A."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, text

import orbitmind.orchestration.tool_gateway_lifecycle as gateway_lifecycle
from orbitmind.admission.contracts import (
    OPERATION_PROFILES,
    AdmissionOperationKind,
    OperationProposal,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.orchestration.admission_lifecycle import admit_operation
from orbitmind.orchestration.tool_gateway_lifecycle import (
    GatewayDisposition,
    GatewayServiceTransactionError,
    evaluate_tool_invocation,
)
from orbitmind.persistence.admission_models import OperationAdmissionRecordRow
from orbitmind.persistence.admission_repository import (
    AdmissionRecordCorruptError,
    SqlAlchemyAdmissionRepository,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.tool_gateway_models import OperationToolGatewayDecisionRow
from orbitmind.toolgateway.catalog import DescriptorResolution, resolve_descriptor
from orbitmind.toolgateway.contracts import (
    GatewayOutcome,
    GatewayReasonCode,
    ToolAvailability,
    ToolInvocationProposal,
    decision_checksum_source,
)

T0 = datetime(2026, 7, 22, tzinfo=UTC)
OWNER = "owner-piyush-01"
OWNER_B = "owner-second-02"
ACTOR = "agent-dev-0001"
SCOPE = ProposalScope(resource_type="repository", resource_id="orbitmind-main")


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(f"sqlite:///{(tmp_path / 'gateway-services.db').as_posix()}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _admission_proposal(
    kind: AdmissionOperationKind,
    *,
    owner: str = OWNER,
    actor: str = ACTOR,
    proposal_id: str = "admission-proposal-0001",
    key: str = "admission-key-0001",
) -> OperationProposal:
    profile = OPERATION_PROFILES[kind]
    return OperationProposal(
        proposal_id=proposal_id,
        owner_id=owner,
        actor_id=actor,
        actor_type=ProposalActorType.AGENT,
        operation_kind=kind.value,
        requested_capability=profile.required_capability,
        requested_scope=SCOPE,
        side_effect_class=profile.side_effect_class,
        risk_class=profile.risk_class,
        purpose="Seed immutable admission evidence.",
        requested_at=T0,
        idempotency_key=key,
    )


def _seed_admission(
    database: Database,
    kind: AdmissionOperationKind = AdmissionOperationKind.READ_REPOSITORY,
    *,
    owner: str = OWNER,
    actor: str = ACTOR,
    proposal_id: str = "admission-proposal-0001",
    key: str = "admission-key-0001",
) -> Any:
    with database.session() as session:
        return admit_operation(
            session=session,
            proposal=_admission_proposal(
                kind, owner=owner, actor=actor, proposal_id=proposal_id, key=key
            ),
            authoritative_owner_id=owner,
            authoritative_actor_id=actor,
            evaluated_at=T0,
        ).record


def _gateway_proposal(
    admission_id: str,
    *,
    tool_id: str = "repository_file_reader",
    input_schema_reference: str = "repository_read_request",
    proposal_id: str = "gateway-proposal-0001",
    key: str = "gateway-key-0001",
    owner: str = OWNER,
    actor: str = ACTOR,
) -> ToolInvocationProposal:
    return ToolInvocationProposal(
        proposal_id=proposal_id,
        owner_id=owner,
        actor_id=actor,
        admission_id=admission_id,
        tool_id=tool_id,
        tool_version="1.0.0",
        input_schema_reference=input_schema_reference,
        purpose="Evaluate a bounded non-executing tool proposal.",
        requested_at=T0,
        idempotency_key=key,
    )


def _evaluate(
    database: Database,
    proposal: ToolInvocationProposal,
    *,
    owner: str = OWNER,
    actor: str = ACTOR,
    evaluated_at: datetime = T0,
) -> Any:
    with database.session() as session:
        return evaluate_tool_invocation(
            session=session,
            proposal=proposal,
            authoritative_owner_id=owner,
            authoritative_actor_id=actor,
            evaluated_at=evaluated_at,
        )


def _gateway_count(database: Database) -> int:
    with database.session() as session:
        return int(
            session.scalar(select(func.count()).select_from(OperationToolGatewayDecisionRow))
        )


def _admission_identity(database: Database, admission_id: str, owner: str = OWNER) -> str:
    with database.session() as session:
        row = session.get(OperationAdmissionRecordRow, (admission_id, owner))
        assert row is not None
        return row.record_identity


def test_service_requires_fresh_session_and_typed_error(database: Database) -> None:
    admission = _seed_admission(database)
    proposal = _gateway_proposal(admission.admission_id)
    with database.session() as session:
        session.execute(text("SELECT 1"))
        with pytest.raises(GatewayServiceTransactionError) as caught:
            evaluate_tool_invocation(
                session=session,
                proposal=proposal,
                authoritative_owner_id=OWNER,
                authoritative_actor_id=ACTOR,
                evaluated_at=T0,
            )
    assert caught.value.code == "tool_gateway_transaction_error"
    assert _gateway_count(database) == 0


def test_fresh_session_durability_close_restart_and_replay(database: Database) -> None:
    admission = _seed_admission(database)
    proposal = _gateway_proposal(admission.admission_id)
    first = _evaluate(database, proposal)
    assert first.disposition is GatewayDisposition.CREATED
    assert first.record.created_at == first.record.evaluated_at == T0

    with database.session() as fresh_session:
        fresh = SqlAlchemyAdmissionRepository(fresh_session).get_verified_admission_record(
            owner_id=OWNER, admission_id=admission.admission_id
        )
        stored = fresh_session.get(
            OperationToolGatewayDecisionRow, (first.record.gateway_decision_id, OWNER)
        )
        assert fresh is not None and stored is not None

    restarted = Database(str(database.engine.url))
    try:
        with restarted.session() as session:
            persisted = gateway_lifecycle.SqlAlchemyToolGatewayRepository(
                session
            ).get_gateway_decision_record(
                owner_id=OWNER, gateway_decision_id=first.record.gateway_decision_id
            )
        replay = _evaluate(restarted, proposal, evaluated_at=T0 + timedelta(days=1))
        assert persisted == first.record
        assert replay.record == first.record
        assert replay.disposition is GatewayDisposition.REPLAYED
        assert _gateway_count(restarted) == 1
    finally:
        restarted.dispose()


def test_restart_conflict_is_read_only(database: Database) -> None:
    admission = _seed_admission(database)
    proposal = _gateway_proposal(admission.admission_id)
    _evaluate(database, proposal)
    restarted = Database(str(database.engine.url))
    try:
        conflicting = proposal.model_copy(update={"purpose": "Different bounded purpose."})
        with pytest.raises(IdempotencyConflictError):
            _evaluate(restarted, conflicting)
        assert _gateway_count(restarted) == 1
    finally:
        restarted.dispose()


@pytest.mark.parametrize(
    ("kind", "tool_id", "schema", "outcome", "reason"),
    [
        (
            AdmissionOperationKind.READ_REPOSITORY,
            "repository_file_reader",
            "repository_read_request",
            GatewayOutcome.ELIGIBLE,
            GatewayReasonCode.ELIGIBLE_BY_POLICY,
        ),
        (
            AdmissionOperationKind.RUN_LOCAL_VALIDATION,
            "local_validation_runner",
            "local_validation_request",
            GatewayOutcome.APPROVAL_REQUIRED,
            GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED,
        ),
        (
            AdmissionOperationKind.PROPOSE_FILE_CHANGE,
            "repository_file_reader",
            "repository_read_request",
            GatewayOutcome.DENIED,
            GatewayReasonCode.ADMISSION_NOT_ADMITTED,
        ),
    ],
)
def test_real_admissions_drive_eligible_approval_and_denied_decisions(
    database: Database,
    kind: AdmissionOperationKind,
    tool_id: str,
    schema: str,
    outcome: GatewayOutcome,
    reason: GatewayReasonCode,
) -> None:
    admission = _seed_admission(database, kind)
    identity = _admission_identity(database, admission.admission_id)
    result = _evaluate(
        database,
        _gateway_proposal(admission.admission_id, tool_id=tool_id, input_schema_reference=schema),
    )
    assert result.record.outcome is outcome
    assert result.record.primary_reason_code is reason
    assert result.record.admission_record_identity == identity
    assert result.record.resolved_admission_id == admission.admission_id
    assert result.record.admission_record_identity != admission.admission_id


def test_missing_and_cross_owner_admission_do_not_leak_or_substitute_identity(
    database: Database,
) -> None:
    missing_id = "admission-missing-0001"
    missing = _evaluate(database, _gateway_proposal(missing_id))
    assert missing.record.primary_reason_code is GatewayReasonCode.ADMISSION_NOT_FOUND
    assert missing.record.resolved_admission_id is None
    assert missing.record.admission_record_identity is None

    foreign = _seed_admission(
        database,
        owner=OWNER_B,
        proposal_id="admission-proposal-0002",
        key="admission-key-0002",
    )
    cross_owner = _evaluate(
        database,
        _gateway_proposal(
            foreign.admission_id,
            proposal_id="gateway-proposal-0002",
            key="gateway-key-0002",
        ),
    )
    assert cross_owner.record.primary_reason_code is GatewayReasonCode.ADMISSION_NOT_FOUND
    assert cross_owner.record.resolved_admission_id is None
    assert cross_owner.record.admission_record_identity is None


@pytest.mark.parametrize("corruption", ["identity", "payload"])
def test_corrupt_admission_rolls_back_and_persists_no_gateway_row(
    database: Database, corruption: str
) -> None:
    admission = _seed_admission(database)
    with database.session() as session, session.begin():
        row = session.get(OperationAdmissionRecordRow, (admission.admission_id, OWNER))
        assert row is not None
        if corruption == "identity":
            row.record_identity = "f" * 64
        else:
            payload = dict(row.canonical_payload)
            payload["operation_kind"] = "run_local_validation"
            row.canonical_payload = payload

    with pytest.raises(AdmissionRecordCorruptError):
        _evaluate(database, _gateway_proposal(admission.admission_id))
    assert _gateway_count(database) == 0


def test_replay_and_conflict_call_no_current_catalog_admission_or_policy(
    database: Database,
) -> None:
    admission = _seed_admission(database)
    proposal = _gateway_proposal(admission.admission_id)
    first = _evaluate(database, proposal)
    with (
        patch.object(gateway_lifecycle, "resolve_descriptor", side_effect=AssertionError),
        patch.object(
            SqlAlchemyAdmissionRepository,
            "get_verified_admission_record",
            side_effect=AssertionError,
        ),
        patch.object(gateway_lifecycle, "evaluate_gateway_proposal", side_effect=AssertionError),
    ):
        replay = _evaluate(database, proposal, evaluated_at=T0 + timedelta(days=1))
        with pytest.raises(IdempotencyConflictError):
            _evaluate(database, proposal.model_copy(update={"purpose": "Changed purpose."}))
    assert replay.disposition is GatewayDisposition.REPLAYED
    assert replay.record == first.record
    assert _gateway_count(database) == 1


def test_new_proposal_evaluates_current_state_and_checksum_binds_verified_identity(
    database: Database,
) -> None:
    admission = _seed_admission(database)
    proposal = _gateway_proposal(admission.admission_id)
    original_read = SqlAlchemyAdmissionRepository.get_verified_admission_record
    original_policy = gateway_lifecycle.evaluate_gateway_proposal
    original_resolution = resolve_descriptor(proposal.tool_id, proposal.tool_version)
    assert original_resolution.descriptor is not None
    disabled_resolution = DescriptorResolution(
        descriptor=original_resolution.descriptor.model_copy(
            update={"availability": ToolAvailability.DISABLED}
        ),
        tool_registered=True,
    )

    def verified_read(
        repository: SqlAlchemyAdmissionRepository, *, owner_id: str, admission_id: str
    ) -> Any:
        return original_read(repository, owner_id=owner_id, admission_id=admission_id)

    with (
        patch.object(
            gateway_lifecycle,
            "resolve_descriptor",
            return_value=disabled_resolution,
        ) as catalog_lookup,
        patch.object(
            SqlAlchemyAdmissionRepository,
            "get_verified_admission_record",
            autospec=True,
            side_effect=verified_read,
        ) as admission_lookup,
        patch.object(
            gateway_lifecycle,
            "evaluate_gateway_proposal",
            wraps=original_policy,
        ) as policy_evaluation,
    ):
        result = _evaluate(database, proposal)
    assert result.record.primary_reason_code is GatewayReasonCode.TOOL_UNAVAILABLE
    assert (
        catalog_lookup.call_count
        == admission_lookup.call_count
        == policy_evaluation.call_count
        == 1
    )

    identity = _admission_identity(database, admission.admission_id)
    assert result.record.admission_record_identity == identity
    expected = sha256_text(
        decision_checksum_source(
            policy_version=result.record.policy_version,
            proposal_fingerprint=result.record.proposal_fingerprint,
            descriptor_checksum=result.record.descriptor_checksum,
            admission_record_identity=identity,
            outcome=result.record.outcome,
            reason_codes=result.record.reason_codes,
            evaluated_at=result.record.evaluated_at,
        )
    )
    assert result.record.decision_checksum == expected
