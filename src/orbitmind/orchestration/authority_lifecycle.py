"""Owner-scoped authority lifecycle application services (U7.2).

This module coordinates the frozen U7.0 contracts with the append-only U7.1
repository.  It owns one fresh SQLAlchemy transaction per explicit command and
does not expose an API, perform an operation, or read an ambient clock.

Rejected approval decisions are durable denial evidence in their own right.
They never create a grant or an authority-evaluation record: evaluations are
strictly questions about existing persisted grants.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Literal
from unicodedata import category

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityEvaluationDecision,
    AuthorityEvaluationRequest,
    AuthorityScope,
    CapabilityGrant,
    DelegationPolicy,
    OperatorReference,
    RevocationRecord,
    SubjectReference,
    ValidityWindow,
)
from orbitmind.authority.evaluation import evaluate_authority
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.persistence.authority_repository import SqlAlchemyAuthorityRepository

_ID_PATTERN = r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$"
_POLICY_PATTERN = r"^[a-z][a-z0-9.-]{2,63}$"
_IDEMPOTENCY_MAX_LENGTH = 200
_FORBIDDEN_TEXT_FRAGMENTS = ("://", "\\", "/", "..")
_FORBIDDEN_TEXT_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")


class AuthorityLifecycleError(ValidationError):
    """Base class for deterministic U7.2 lifecycle rejections."""

    code = "authority_lifecycle_error"


class AuthorityRequestNotFoundError(NotFoundError):
    """The owner-scoped approval request does not exist."""

    code = "authority_request_not_found"


class AuthorityDecisionNotFoundError(NotFoundError):
    """The owner-scoped approval decision does not exist."""

    code = "authority_decision_not_found"


class AuthorityGrantNotFoundError(NotFoundError):
    """The owner-scoped capability grant does not exist."""

    code = "authority_grant_not_found"


class AuthorityRequestAlreadyDecidedError(AuthorityLifecycleError):
    """An approval request already has a terminal decision."""

    code = "authority_request_already_decided"


class AuthorityDecisionRejectedError(AuthorityLifecycleError):
    """A rejected decision cannot create or evaluate a grant chain."""

    code = "authority_decision_rejected"


class AuthorityPolicyMismatchError(AuthorityLifecycleError):
    """A command policy differs from the persisted authority policy."""

    code = "authority_policy_mismatch"


class AuthorityChainMismatchError(AuthorityLifecycleError):
    """Stored records do not form the command's exact authority chain."""

    code = "authority_chain_mismatch"


class AuthorityLifecycleTransactionError(AuthorityLifecycleError):
    """A lifecycle service requires a fresh caller-provided session."""

    code = "authority_transaction_error"


class _StrictLifecycleModel(BaseModel):
    """Closed, immutable, coercion-free U7.2 application contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class _LifecycleCommand(_StrictLifecycleModel):
    """Common explicit identity, policy, and replay metadata."""

    schema_version: Literal["authority-contracts-v1"] = "authority-contracts-v1"
    owner_id: str = Field(pattern=_ID_PATTERN)
    policy_version: str = Field(pattern=_POLICY_PATTERN)
    idempotency_key: str = Field(min_length=1, max_length=_IDEMPOTENCY_MAX_LENGTH)

    @field_validator("idempotency_key")
    @classmethod
    def _canonical_idempotency_key(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("idempotency_key must not have surrounding whitespace")
        return value

    @field_validator("policy_version")
    @classmethod
    def _safe_policy_version(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("policy_version must not contain '..'")
        return value


class CreateApprovalRequestCommand(_LifecycleCommand):
    """Explicit non-authoritative request creation command."""

    request_id: str = Field(pattern=_ID_PATTERN)
    requested_by: str = Field(pattern=_ID_PATTERN)
    subject: SubjectReference
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    scope: AuthorityScope
    purpose: str = Field(min_length=1, max_length=300)
    requested_at: datetime
    valid_from: datetime
    expires_at: datetime

    @field_validator("requested_at", "valid_from", "expires_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")

    @model_validator(mode="after")
    def _validity_window(self) -> CreateApprovalRequestCommand:
        _validate_validity_window(self.valid_from, self.expires_at)
        return self


class RecordApprovalDecisionCommand(_LifecycleCommand):
    """Explicit terminal human approval-decision command."""

    decision_id: str = Field(pattern=_ID_PATTERN)
    request_id: str = Field(pattern=_ID_PATTERN)
    decided_by: OperatorReference
    outcome: ApprovalDecisionOutcome
    decided_at: datetime
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("decided_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("reason")
    @classmethod
    def _safe_reason(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="reason")


class IssueCapabilityGrantCommand(_LifecycleCommand):
    """Explicit issuance command that can only use stored approval truth."""

    grant_id: str = Field(pattern=_ID_PATTERN)
    request_id: str = Field(pattern=_ID_PATTERN)
    decision_id: str = Field(pattern=_ID_PATTERN)
    issued_by: OperatorReference
    issued_at: datetime
    valid_from: datetime
    expires_at: datetime
    delegation: Literal[DelegationPolicy.PROHIBITED] = DelegationPolicy.PROHIBITED

    @field_validator("issued_at", "valid_from", "expires_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _validity_window(self) -> IssueCapabilityGrantCommand:
        _validate_validity_window(self.valid_from, self.expires_at)
        return self


class RevokeCapabilityGrantCommand(_LifecycleCommand):
    """Explicit append-only grant-revocation command."""

    revocation_id: str = Field(pattern=_ID_PATTERN)
    grant_id: str = Field(pattern=_ID_PATTERN)
    revoked_by: str = Field(pattern=_ID_PATTERN)
    effective_at: datetime
    recorded_at: datetime
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("effective_at", "recorded_at")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("reason")
    @classmethod
    def _safe_reason(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="reason")


class EvaluateAuthorityCommand(_LifecycleCommand):
    """Explicit question about one existing persisted grant at one known time."""

    evaluation_id: str = Field(pattern=_ID_PATTERN)
    request_id: str = Field(pattern=_ID_PATTERN)
    decision_id: str = Field(pattern=_ID_PATTERN)
    grant_id: str = Field(pattern=_ID_PATTERN)
    subject: SubjectReference
    capability: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    scope: AuthorityScope
    purpose: str = Field(min_length=1, max_length=300)
    evaluation_time: datetime
    delegation_requested: bool = False

    @field_validator("evaluation_time")
    @classmethod
    def _utc_time(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")


class AuthorityChainReadModel(_StrictLifecycleModel):
    """Truthful stored authority evidence for one owner-scoped request.

    This is deliberately not a mutable lifecycle-status record.  A pending,
    rejected, approved-ungranted, or granted state is evident from the stored
    tuples and never inferred from a system clock.
    """

    owner_id: str = Field(pattern=_ID_PATTERN)
    approval_request: ApprovalRequest
    approval_decisions: tuple[ApprovalDecision, ...]
    capability_grants: tuple[CapabilityGrant, ...]
    revocations: tuple[RevocationRecord, ...]
    evaluations: tuple[AuthorityEvaluationDecision, ...]


def create_approval_request(
    *, session: Session, command: CreateApprovalRequestCommand
) -> ApprovalRequest:
    """Persist exactly one non-authoritative approval request."""

    def operation(repository: SqlAlchemyAuthorityRepository) -> ApprovalRequest:
        request = ApprovalRequest(
            request_id=command.request_id,
            owner_id=command.owner_id,
            requested_by=command.requested_by,
            subject=command.subject,
            capability=command.capability,
            scope=command.scope,
            purpose=command.purpose,
            policy_version=command.policy_version,
            requested_at=command.requested_at,
            validity=ValidityWindow(valid_from=command.valid_from, expires_at=command.expires_at),
        )
        return repository.append_approval_request(request, idempotency_key=command.idempotency_key)

    return _mutate(session, operation)


def record_approval_decision(
    *, session: Session, command: RecordApprovalDecisionCommand
) -> ApprovalDecision:
    """Append one terminal decision; replay is the sole exception to uniqueness."""

    def operation(repository: SqlAlchemyAuthorityRepository) -> ApprovalDecision:
        request = _require_locked_request(repository, command.owner_id, command.request_id)
        _require_matching_policy(command.policy_version, request.policy_version)
        if command.decided_at < request.requested_at:
            raise AuthorityChainMismatchError("approval decision precedes its request")
        decision = ApprovalDecision(
            decision_id=command.decision_id,
            request_id=request.request_id,
            owner_id=request.owner_id,
            decided_by=command.decided_by,
            outcome=command.outcome,
            decided_at=command.decided_at,
            reason=command.reason,
            subject=request.subject,
            capability=request.capability,
            scope=request.scope,
            purpose=request.purpose,
            policy_version=request.policy_version,
            validity=request.validity,
        )
        existing = _decisions_for_request(repository, command.owner_id, command.request_id)
        if existing:
            if len(existing) != 1:
                raise AuthorityChainMismatchError("stored request has multiple terminal decisions")
            if existing[0] != decision:
                raise AuthorityRequestAlreadyDecidedError(
                    "approval request already has a terminal decision"
                )
        return repository.append_approval_decision(
            decision, idempotency_key=command.idempotency_key
        )

    return _mutate(session, operation)


def issue_capability_grant(
    *, session: Session, command: IssueCapabilityGrantCommand
) -> CapabilityGrant:
    """Append an explicit grant reconstructed from one approved stored decision."""

    def operation(repository: SqlAlchemyAuthorityRepository) -> CapabilityGrant:
        request = _require_request(repository, command.owner_id, command.request_id)
        decision = _require_decision(repository, command.owner_id, command.decision_id)
        _require_decision_for_request(decision, request)
        _require_matching_policy(command.policy_version, request.policy_version)
        _require_matching_policy(command.policy_version, decision.policy_version)
        if decision.outcome is ApprovalDecisionOutcome.REJECTED:
            raise AuthorityDecisionRejectedError("rejected approval decisions cannot issue grants")
        if command.issued_at < decision.decided_at:
            raise AuthorityChainMismatchError("grant issuance precedes its approval decision")
        if (command.valid_from, command.expires_at) != (
            decision.validity.valid_from,
            decision.validity.expires_at,
        ):
            raise AuthorityChainMismatchError("grant validity must exactly match its approval")
        grant = CapabilityGrant(
            grant_id=command.grant_id,
            owner_id=request.owner_id,
            request_id=request.request_id,
            decision_id=decision.decision_id,
            issued_by=command.issued_by,
            issued_at=command.issued_at,
            subject=request.subject,
            capability=request.capability,
            scope=request.scope,
            purpose=request.purpose,
            policy_version=request.policy_version,
            validity=request.validity,
            delegation=command.delegation,
        )
        return repository.append_capability_grant(grant, idempotency_key=command.idempotency_key)

    return _mutate(session, operation)


def revoke_capability_grant(
    *, session: Session, command: RevokeCapabilityGrantCommand
) -> RevocationRecord:
    """Append one revocation without mutating the grant it names."""

    def operation(repository: SqlAlchemyAuthorityRepository) -> RevocationRecord:
        grant = _require_grant(repository, command.owner_id, command.grant_id)
        _require_matching_policy(command.policy_version, grant.policy_version)
        revocation = RevocationRecord(
            revocation_id=command.revocation_id,
            grant_id=grant.grant_id,
            owner_id=grant.owner_id,
            revoked_by=command.revoked_by,
            effective_at=command.effective_at,
            recorded_at=command.recorded_at,
            reason=command.reason,
        )
        return repository.append_revocation(revocation, idempotency_key=command.idempotency_key)

    return _mutate(session, operation)


def evaluate_authority_command(
    *, session: Session, command: EvaluateAuthorityCommand
) -> AuthorityEvaluationDecision:
    """Evaluate and append evidence for one existing exact persisted grant chain."""

    def operation(repository: SqlAlchemyAuthorityRepository) -> AuthorityEvaluationDecision:
        request = _require_request(repository, command.owner_id, command.request_id)
        decision = _require_decision(repository, command.owner_id, command.decision_id)
        _require_decision_for_request(decision, request)
        if decision.outcome is ApprovalDecisionOutcome.REJECTED:
            raise AuthorityDecisionRejectedError(
                "rejected approval decisions have no grant to evaluate"
            )
        grant = _require_grant(repository, command.owner_id, command.grant_id)
        _require_grant_for_decision(grant, request, decision)
        evaluation_request = AuthorityEvaluationRequest(
            evaluation_id=command.evaluation_id,
            owner_id=command.owner_id,
            evaluation_time=command.evaluation_time,
            subject=command.subject,
            capability=command.capability,
            scope=command.scope,
            purpose=command.purpose,
            policy_version=command.policy_version,
            delegation_requested=command.delegation_requested,
            approval_request=request,
            approval_decision=decision,
            grant=grant,
            revocations=repository.list_revocations_for_grant(
                owner_id=command.owner_id, grant_id=grant.grant_id
            ),
        )
        decision_result = evaluate_authority(evaluation_request)
        return repository.append_evaluation_record(
            evaluation_request,
            decision_result,
            idempotency_key=command.idempotency_key,
        )

    return _mutate(session, operation)


def read_authority_chain(
    *, session: Session, owner_id: str, request_id: str
) -> AuthorityChainReadModel | None:
    """Read all persisted evidence for one owner-scoped approval request."""

    def operation(repository: SqlAlchemyAuthorityRepository) -> AuthorityChainReadModel | None:
        request = repository.get_approval_request(owner_id=owner_id, request_id=request_id)
        if request is None:
            return None
        decisions = _decisions_for_request(repository, owner_id, request_id)
        if len(decisions) > 1:
            raise AuthorityChainMismatchError("stored request has multiple terminal decisions")
        grants = tuple(
            grant
            for grant in repository.list_capability_grants(owner_id=owner_id)
            if grant.request_id == request_id
        )
        if decisions:
            decision = decisions[0]
            _require_decision_for_request(decision, request)
            for grant in grants:
                _require_grant_for_decision(grant, request, decision)
        elif grants:
            raise AuthorityChainMismatchError("stored grants have no terminal decision")
        revocations = tuple(
            revocation
            for grant in grants
            for revocation in repository.list_revocations_for_grant(
                owner_id=owner_id, grant_id=grant.grant_id
            )
        )
        evaluations = tuple(
            evaluation
            for grant in grants
            for evaluation in repository.list_evaluations(
                owner_id=owner_id, grant_id=grant.grant_id
            )
        )
        return AuthorityChainReadModel(
            owner_id=owner_id,
            approval_request=request,
            approval_decisions=decisions,
            capability_grants=grants,
            revocations=revocations,
            evaluations=evaluations,
        )

    return _read(session, operation)


def list_approval_requests(*, session: Session, owner_id: str) -> tuple[ApprovalRequest, ...]:
    """Return one owner's stored requests in repository-defined deterministic order."""

    return _read(session, lambda repository: repository.list_approval_requests(owner_id=owner_id))


def list_approval_decisions(*, session: Session, owner_id: str) -> tuple[ApprovalDecision, ...]:
    """Return one owner's stored decisions in repository-defined deterministic order."""

    return _read(session, lambda repository: repository.list_approval_decisions(owner_id=owner_id))


def list_capability_grants(*, session: Session, owner_id: str) -> tuple[CapabilityGrant, ...]:
    """Return one owner's stored grants in repository-defined deterministic order."""

    return _read(session, lambda repository: repository.list_capability_grants(owner_id=owner_id))


def list_revocations_for_grant(
    *, session: Session, owner_id: str, grant_id: str
) -> tuple[RevocationRecord, ...]:
    """Return revocations for one exact owner-scoped grant, or an empty tuple."""

    return _read(
        session,
        lambda repository: repository.list_revocations_for_grant(
            owner_id=owner_id, grant_id=grant_id
        ),
    )


def list_evaluations_for_grant(
    *, session: Session, owner_id: str, grant_id: str
) -> tuple[AuthorityEvaluationDecision, ...]:
    """Return grant-backed evaluation evidence for one exact owner-scoped grant."""

    return _read(
        session,
        lambda repository: repository.list_evaluations(owner_id=owner_id, grant_id=grant_id),
    )


def _mutate[ResultT](
    session: Session, operation: Callable[[SqlAlchemyAuthorityRepository], ResultT]
) -> ResultT:
    _require_fresh_session(session)
    with session.begin():
        return operation(SqlAlchemyAuthorityRepository(session))


def _read[ResultT](
    session: Session, operation: Callable[[SqlAlchemyAuthorityRepository], ResultT]
) -> ResultT:
    _require_fresh_session(session)
    with session.begin():
        return operation(SqlAlchemyAuthorityRepository(session))


def _require_fresh_session(session: Session) -> None:
    if session.in_transaction():
        raise AuthorityLifecycleTransactionError("authority lifecycle requires a fresh session")


def _require_request(
    repository: SqlAlchemyAuthorityRepository, owner_id: str, request_id: str
) -> ApprovalRequest:
    request = repository.get_approval_request(owner_id=owner_id, request_id=request_id)
    if request is None:
        raise AuthorityRequestNotFoundError("authority approval request was not found")
    return request


def _require_locked_request(
    repository: SqlAlchemyAuthorityRepository, owner_id: str, request_id: str
) -> ApprovalRequest:
    request = repository.read_approval_request_for_update(owner_id=owner_id, request_id=request_id)
    if request is None:
        raise AuthorityRequestNotFoundError("authority approval request was not found")
    return request


def _require_decision(
    repository: SqlAlchemyAuthorityRepository, owner_id: str, decision_id: str
) -> ApprovalDecision:
    decision = repository.get_approval_decision(owner_id=owner_id, decision_id=decision_id)
    if decision is None:
        raise AuthorityDecisionNotFoundError("authority approval decision was not found")
    return decision


def _require_grant(
    repository: SqlAlchemyAuthorityRepository, owner_id: str, grant_id: str
) -> CapabilityGrant:
    grant = repository.get_capability_grant(owner_id=owner_id, grant_id=grant_id)
    if grant is None:
        raise AuthorityGrantNotFoundError("authority capability grant was not found")
    return grant


def _require_matching_policy(command_policy: str, stored_policy: str) -> None:
    if command_policy != stored_policy:
        raise AuthorityPolicyMismatchError("authority policy does not match persisted evidence")


def _validate_validity_window(valid_from: datetime, expires_at: datetime) -> None:
    ValidityWindow(valid_from=valid_from, expires_at=expires_at)


def _validate_safe_text(value: str, *, field_name: str) -> str:
    for character in value:
        if character == "\x7f" or category(character) in _FORBIDDEN_TEXT_CATEGORIES:
            raise ValueError(
                f"{field_name} must be a single line without control or invisible characters"
            )
    for fragment in _FORBIDDEN_TEXT_FRAGMENTS:
        if fragment in value:
            raise ValueError(f"{field_name} must not contain path or URL fragments ({fragment!r})")
    if "*" in value:
        raise ValueError(f"{field_name} must not contain wildcards")
    return value


def _require_decision_for_request(decision: ApprovalDecision, request: ApprovalRequest) -> None:
    if (
        decision.owner_id != request.owner_id
        or decision.request_id != request.request_id
        or decision.subject != request.subject
        or decision.capability != request.capability
        or decision.scope != request.scope
        or decision.purpose != request.purpose
        or decision.policy_version != request.policy_version
        or decision.validity != request.validity
        or decision.decided_at < request.requested_at
    ):
        raise AuthorityChainMismatchError("approval decision does not match its stored request")


def _require_grant_for_decision(
    grant: CapabilityGrant, request: ApprovalRequest, decision: ApprovalDecision
) -> None:
    if (
        grant.owner_id != request.owner_id
        or grant.request_id != request.request_id
        or grant.decision_id != decision.decision_id
        or grant.subject != decision.subject
        or grant.capability != decision.capability
        or grant.scope != decision.scope
        or grant.purpose != decision.purpose
        or grant.policy_version != decision.policy_version
        or grant.validity != decision.validity
        or grant.issued_at < decision.decided_at
    ):
        raise AuthorityChainMismatchError("capability grant does not match persisted approval")


def _decisions_for_request(
    repository: SqlAlchemyAuthorityRepository, owner_id: str, request_id: str
) -> tuple[ApprovalDecision, ...]:
    return tuple(
        decision
        for decision in repository.list_approval_decisions(owner_id=owner_id)
        if decision.request_id == request_id
    )
