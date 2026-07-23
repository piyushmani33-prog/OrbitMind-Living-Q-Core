"""The only U8.1A bridge from Admission evidence to gateway decision evidence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from orbitmind.admission.contracts import AdmissionOutcome
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import ValidationError
from orbitmind.persistence.admission_repository import SqlAlchemyAdmissionRepository
from orbitmind.persistence.tool_gateway_repository import (
    GatewayDisposition,
    GatewayWriteResult,
    SqlAlchemyToolGatewayRepository,
)
from orbitmind.toolgateway.catalog import resolve_descriptor
from orbitmind.toolgateway.contracts import (
    AdmissionFinding,
    GatewayDecisionRecord,
    GatewayEvaluationContext,
    ToolInvocationProposal,
    decision_checksum_source,
    descriptor_checksum,
    fingerprint_source,
)
from orbitmind.toolgateway.policy import evaluate_gateway_proposal


class GatewayServiceTransactionError(ValidationError):
    code = "tool_gateway_transaction_error"


def evaluate_tool_invocation(
    *,
    session: Session,
    proposal: ToolInvocationProposal,
    authoritative_owner_id: str,
    authoritative_actor_id: str,
    evaluated_at: datetime,
) -> GatewayWriteResult:
    if session.in_transaction():
        raise GatewayServiceTransactionError("tool gateway requires a fresh session")
    context = GatewayEvaluationContext(
        authoritative_owner_id=authoritative_owner_id,
        authoritative_actor_id=authoritative_actor_id,
        evaluated_at=evaluated_at,
    )
    with session.begin():
        fingerprint = sha256_text(fingerprint_source(proposal, context))
        repo = SqlAlchemyToolGatewayRepository(session)
        historical = repo.resolve_historical_replay(
            owner_id=authoritative_owner_id,
            idempotency_key=proposal.idempotency_key,
            proposal_fingerprint=fingerprint,
        )
        if historical is not None:
            return GatewayWriteResult(historical, GatewayDisposition.REPLAYED)
        verified = SqlAlchemyAdmissionRepository(session).get_verified_admission_record(
            owner_id=authoritative_owner_id, admission_id=proposal.admission_id
        )
        admission = None if verified is None else verified.record
        admission_record_identity = None if verified is None else verified.record_identity
        finding = AdmissionFinding(
            found=verified is not None,
            admitted=admission is not None and admission.outcome is AdmissionOutcome.ADMITTED,
            actor_id=None if admission is None else admission.actor_id,
            operation_kind=None if admission is None else admission.operation_kind,
            admission_record_identity=admission_record_identity,
        )
        resolution = resolve_descriptor(proposal.tool_id, proposal.tool_version)
        resolved_descriptor_checksum = (
            None if resolution.descriptor is None else descriptor_checksum(resolution.descriptor)
        )
        decision = evaluate_gateway_proposal(proposal, context, finding, resolution)
        checksum = sha256_text(
            decision_checksum_source(
                policy_version=decision.policy_version,
                proposal_fingerprint=fingerprint,
                descriptor_checksum=resolved_descriptor_checksum,
                admission_record_identity=admission_record_identity,
                outcome=decision.outcome,
                reason_codes=decision.reason_codes,
                evaluated_at=decision.evaluated_at,
            )
        )
        record = GatewayDecisionRecord(
            gateway_decision_id="tgd-"
            + sha256_text(authoritative_owner_id + "\x1e" + proposal.idempotency_key)[:40],
            owner_id=authoritative_owner_id,
            proposal_id=proposal.proposal_id,
            actor_id=authoritative_actor_id,
            tool_id=proposal.tool_id,
            tool_version=proposal.tool_version,
            descriptor_checksum=resolved_descriptor_checksum,
            referenced_admission_id=proposal.admission_id,
            resolved_admission_id=None if admission is None else admission.admission_id,
            admission_record_identity=admission_record_identity,
            outcome=decision.outcome,
            primary_reason_code=decision.primary_reason_code,
            reason_codes=decision.reason_codes,
            evaluated_at=decision.evaluated_at,
            requested_at=proposal.requested_at,
            proposal_fingerprint=fingerprint,
            decision_checksum=checksum,
            created_at=context.evaluated_at,
        )
        return repo.append_gateway_decision_record(record, idempotency_key=proposal.idempotency_key)
