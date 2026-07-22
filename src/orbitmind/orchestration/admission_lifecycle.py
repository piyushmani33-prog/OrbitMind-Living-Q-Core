"""Owner-scoped Operation Admission v0 application service (U7.4).

This is the **only** place Operation Admission touches Authority. It builds the
trusted evaluation context, distills owner-scoped Authority evidence into an
admission-native :class:`AuthorityFinding` (reusing the pure
:func:`~orbitmind.authority.evaluation.evaluate_authority` at the single injected
``evaluated_at``), invokes the pure admission policy, and persists one immutable
admission record. It owns one fresh transaction per call, executes nothing, and
reads no ambient clock (``evaluated_at`` is injected by the trusted caller).

The admission *domain* (:mod:`orbitmind.admission`) never imports Authority; this
orchestration layer is the sanctioned bridge.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy.orm import Session

from orbitmind.admission.contracts import (
    OPERATION_ADMISSION_POLICY_VERSION,
    AdmissionEvaluationContext,
    AdmissionReasonCode,
    AdmissionRecord,
    AuthorityFinding,
    OperationProfile,
    OperationProposal,
    ProposalScope,
    decision_checksum_source,
    fingerprint_source,
)
from orbitmind.admission.policy import (
    evaluate_admission,
    operation_profile,
    resolve_operation_kind,
)
from orbitmind.authority.contracts import (
    AuthorityEvaluationRequest,
    AuthorityReasonCode,
    AuthorityScope,
    ScopeConstraint,
    SubjectReference,
    SubjectType,
)
from orbitmind.authority.evaluation import evaluate_authority
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import ValidationError
from orbitmind.persistence.admission_repository import (
    AdmissionDisposition as AdmissionDisposition,
)
from orbitmind.persistence.admission_repository import (
    AdmissionWriteResult,
    SqlAlchemyAdmissionRepository,
)
from orbitmind.persistence.authority_repository import SqlAlchemyAuthorityRepository

_ADMISSION_ID_SEP: Final = "\x1e"

# Authority reason code -> admission reason code. Only the codes reachable when the
# bridge sources purpose/policy from the resolved grant and requests no delegation
# are mapped; any other (structurally unreachable) code fails closed in the policy.
_AUTHORITY_REASON_MAP: Final[dict[AuthorityReasonCode, AdmissionReasonCode]] = {
    AuthorityReasonCode.SUBJECT_MISMATCH: AdmissionReasonCode.AUTHORITY_ACTOR_MISMATCH,
    AuthorityReasonCode.CAPABILITY_MISMATCH: AdmissionReasonCode.CAPABILITY_MISMATCH,
    AuthorityReasonCode.SCOPE_MISMATCH: AdmissionReasonCode.SCOPE_MISMATCH,
    AuthorityReasonCode.NOT_YET_VALID: AdmissionReasonCode.AUTHORITY_NOT_YET_VALID,
    AuthorityReasonCode.EXPIRED: AdmissionReasonCode.AUTHORITY_EXPIRED,
    AuthorityReasonCode.REVOKED: AdmissionReasonCode.AUTHORITY_REVOKED,
}


class AdmissionServiceTransactionError(ValidationError):
    """A fresh caller-provided session is required for one admission."""

    code = "admission_transaction_error"


def _admission_id(owner_id: str, idempotency_key: str) -> str:
    digest = sha256_text(f"{owner_id}{_ADMISSION_ID_SEP}{idempotency_key}")
    return f"adm-{digest[:40]}"


def _authority_scope(scope: ProposalScope) -> AuthorityScope:
    return AuthorityScope(
        resource_type=scope.resource_type,
        resource_id=scope.resource_id,
        constraints=tuple(
            ScopeConstraint(name=constraint.name, value=constraint.value)
            for constraint in scope.constraints
        ),
    )


def _authority_finding(
    authority: SqlAlchemyAuthorityRepository,
    context: AdmissionEvaluationContext,
    proposal: OperationProposal,
    profile: OperationProfile,
) -> AuthorityFinding:
    """Distil owner-scoped Authority evidence, evaluated at ``context.evaluated_at``."""
    if not profile.authority_required:
        return AuthorityFinding(required=False, referenced=False, resolved=False, authorized=False)
    grant_id = proposal.requested_authority_grant_id
    if grant_id is None:
        return AuthorityFinding(required=True, referenced=False, resolved=False, authorized=False)

    owner = context.authoritative_owner_id
    grant = authority.get_capability_grant(owner_id=owner, grant_id=grant_id)
    request = (
        authority.get_approval_request(owner_id=owner, request_id=grant.request_id)
        if grant is not None
        else None
    )
    decision = (
        authority.get_approval_decision(owner_id=owner, decision_id=grant.decision_id)
        if grant is not None
        else None
    )
    if grant is None or request is None or decision is None:
        # Owner-scoped miss (or an inconsistent stored chain): public-safe not-found;
        # never reveal cross-owner existence.
        return AuthorityFinding(required=True, referenced=True, resolved=False, authorized=False)

    evaluation_request = AuthorityEvaluationRequest(
        evaluation_id=proposal.proposal_id,
        owner_id=owner,
        evaluation_time=context.evaluated_at,
        subject=SubjectReference(
            subject_type=SubjectType(proposal.actor_type.value), subject_id=proposal.actor_id
        ),
        capability=profile.required_capability,
        scope=_authority_scope(proposal.requested_scope),
        # purpose and policy_version are sourced from the resolved grant: admission v0
        # verifies actor/capability/scope/validity/revocation, not authority purpose or
        # the authority policy-version namespace.
        purpose=grant.purpose,
        policy_version=grant.policy_version,
        delegation_requested=False,
        approval_request=request,
        approval_decision=decision,
        grant=grant,
        revocations=authority.list_revocations_for_grant(owner_id=owner, grant_id=grant_id),
    )
    result = evaluate_authority(evaluation_request)
    if result.authorized:
        return AuthorityFinding(
            required=True,
            referenced=True,
            resolved=True,
            authorized=True,
            resolved_grant_id=grant_id,
        )
    return AuthorityFinding(
        required=True,
        referenced=True,
        resolved=True,
        authorized=False,
        reason=_AUTHORITY_REASON_MAP.get(result.reason_code),
        resolved_grant_id=grant_id,
    )


def admit_operation(
    *,
    session: Session,
    proposal: OperationProposal,
    authoritative_owner_id: str,
    authoritative_actor_id: str,
    evaluated_at: datetime,
) -> AdmissionWriteResult:
    """Deterministically admit one proposed operation and persist the evidence.

    ``authoritative_owner_id`` / ``authoritative_actor_id`` come from the trusted
    boundary (never from the proposal body); ``evaluated_at`` is the single
    injected trusted timestamp. A visible historical replay is resolved before
    either policy evaluation. Concurrent first writers may both evaluate after
    observing an initial miss; append-time race reconciliation remains authoritative.
    Executes nothing.
    """
    if session.in_transaction():
        raise AdmissionServiceTransactionError("admission service requires a fresh session")

    context = AdmissionEvaluationContext(
        authoritative_owner_id=authoritative_owner_id,
        authoritative_actor_id=authoritative_actor_id,
        evaluated_at=evaluated_at,
        policy_version=OPERATION_ADMISSION_POLICY_VERSION,
    )

    with session.begin():
        admission_repo = SqlAlchemyAdmissionRepository(session)

        fingerprint = sha256_text(fingerprint_source(proposal, context))
        historical = admission_repo.resolve_historical_replay(
            owner_id=authoritative_owner_id,
            idempotency_key=proposal.idempotency_key,
            proposal_fingerprint=fingerprint,
        )
        if historical is not None:
            return AdmissionWriteResult(
                record=historical,
                disposition=AdmissionDisposition.REPLAYED,
            )

        authority_repo = SqlAlchemyAuthorityRepository(session)
        kind = resolve_operation_kind(proposal.operation_kind)
        if kind is not None:
            profile = operation_profile(kind)
            finding = _authority_finding(authority_repo, context, proposal, profile)
        else:
            finding = AuthorityFinding(
                required=False, referenced=False, resolved=False, authorized=False
            )

        decision = evaluate_admission(proposal, context, finding)

        checksum = sha256_text(
            decision_checksum_source(
                policy_version=decision.policy_version,
                proposal_fingerprint=fingerprint,
                outcome=decision.outcome,
                reason_codes=decision.reason_codes,
                evaluated_at=decision.evaluated_at,
                resolved_grant_id=decision.resolved_grant_id,
            )
        )
        record = AdmissionRecord(
            admission_id=_admission_id(authoritative_owner_id, proposal.idempotency_key),
            owner_id=authoritative_owner_id,
            proposal_id=proposal.proposal_id,
            actor_id=authoritative_actor_id,
            actor_type=proposal.actor_type,
            operation_kind=proposal.operation_kind,
            requested_capability=proposal.requested_capability,
            requested_scope=proposal.requested_scope,
            side_effect_class=proposal.side_effect_class,
            risk_class=proposal.risk_class,
            outcome=decision.outcome,
            primary_reason_code=decision.primary_reason_code,
            reason_codes=decision.reason_codes,
            policy_version=decision.policy_version,
            evaluated_at=decision.evaluated_at,
            requested_at=proposal.requested_at,
            requested_authority_grant_id=proposal.requested_authority_grant_id,
            resolved_authority_grant_id=decision.resolved_grant_id,
            proposal_fingerprint=fingerprint,
            decision_checksum=checksum,
            created_at=evaluated_at,
            provenance_refs=proposal.provenance_refs,
        )
        return admission_repo.append_admission_record(
            record, idempotency_key=proposal.idempotency_key
        )
