"""Append-only, owner-scoped persistence for U7 authority evidence (U7.1).

This repository stores and reads the U7.0 authority contracts as immutable
evidence. It exposes only ``append_*`` / ``get_*`` / ``list_*`` operations and
one read-only authority-chain projection. It intentionally has **no** update,
delete, approve, reject, issue, evaluate, or execute operation — those
lifecycle verbs belong to U7.2+.

Guarantees enforced here (with database constraints as defense in depth):

- **Owner scoping**: every read and write is owner-qualified; owner-qualified
  foreign keys make cross-owner links impossible.
- **Append-only**: no mutation of any stored record; duplicate ids fail.
- **Causality**: a decision references an existing same-owner request and
  echoes it; a grant references an existing same-owner *approved* decision and
  echoes it exactly; a revocation references an existing same-owner grant; an
  evaluation references the exact same-owner grant/decision/request chain and
  its stored result is re-derived from the deterministic evaluator.
- **Idempotency**: an ``(owner_id, idempotency_key)`` replay with an identical
  canonical payload returns the stored record; a conflicting payload fails
  closed with ``IdempotencyConflictError``.
- **Fail-closed reads**: row-to-domain re-parses the stored canonical payload
  through the frozen U7.0 contract, so tampered or unknown data raises.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.authority.contracts import (
    ApprovalDecision,
    ApprovalDecisionOutcome,
    ApprovalRequest,
    AuthorityEvaluationDecision,
    AuthorityEvaluationRequest,
    AuthorityReasonCode,
    CapabilityGrant,
    RevocationRecord,
    canonical_authority_json,
    parse_authority_json,
)
from orbitmind.authority.evaluation import evaluate_authority
from orbitmind.core.checksums import sha256_bytes
from orbitmind.core.errors import IdempotencyConflictError, ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.persistence.authority_models import (
    AuthorityApprovalDecisionRow,
    AuthorityApprovalRequestRow,
    AuthorityCapabilityGrantRow,
    AuthorityEvaluationRow,
    AuthorityRevocationRow,
)

_REQUEST_IDENTITY = b"orbitmind-authority-request-identity-v1\x00"
_DECISION_IDENTITY = b"orbitmind-authority-decision-identity-v1\x00"
_GRANT_IDENTITY = b"orbitmind-authority-grant-identity-v1\x00"
_REVOCATION_IDENTITY = b"orbitmind-authority-revocation-identity-v1\x00"
_EVALUATION_IDENTITY = b"orbitmind-authority-evaluation-identity-v1\x00"
_PAYLOAD_SEP = "\x1e"


class AuthorityCausalityError(ValidationError):
    """A record references a missing, cross-owner, or inconsistent chain."""

    code = "authority_causality_error"


class AuthorityRecordCorruptError(ValidationError):
    """A stored authority record failed fail-closed re-parsing on read."""

    code = "authority_record_corrupt"


class _IdempotentRow(Protocol):
    record_identity: str


def _identity(domain_separator: bytes, canonical_json: str) -> str:
    return sha256_bytes(domain_separator + canonical_json.encode("utf-8"))


@dataclass(frozen=True)
class AuthorityChainProjection:
    """Immutable read-only projection of one grant's persisted authority chain."""

    approval_request: ApprovalRequest | None
    approval_decision: ApprovalDecision | None
    grant: CapabilityGrant
    revocations: tuple[RevocationRecord, ...]
    evaluations: tuple[AuthorityEvaluationDecision, ...]


@dataclass(frozen=True)
class _PersistedEvaluationChain:
    """Canonical stored records required to append one evaluation evidence row."""

    approval_request: ApprovalRequest
    approval_decision: ApprovalDecision
    grant: CapabilityGrant
    revocations: tuple[RevocationRecord, ...]


class SqlAlchemyAuthorityRepository:
    """Owner-scoped append-only repository over one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._s = session
        # pysqlite does not participate in SAVEPOINT-based outer rollback; the
        # existing repositories disable savepoints on SQLite and rely on the
        # deterministic pre-checks below. PostgreSQL keeps savepoint recovery.
        self._use_savepoint = session.get_bind().dialect.name != "sqlite"

    # -- approval requests ---------------------------------------------------

    def append_approval_request(
        self, request: ApprovalRequest, *, idempotency_key: str
    ) -> ApprovalRequest:
        canonical = canonical_authority_json(request)
        identity = _identity(_REQUEST_IDENTITY, canonical)
        resolved = self._resolve_replay(
            self._existing_request(request.owner_id, idempotency_key),
            self._existing_request_by_id(request.owner_id, request.request_id),
            identity,
        )
        if resolved is not None:
            return self._request_to_domain(resolved)
        row = AuthorityApprovalRequestRow(
            id=request.request_id,
            owner_id=request.owner_id,
            schema_version=request.schema_version,
            requested_by=request.requested_by,
            subject_type=request.subject.subject_type.value,
            subject_id=request.subject.subject_id,
            capability=request.capability,
            policy_version=request.policy_version,
            requested_at=request.requested_at,
            valid_from=request.validity.valid_from,
            expires_at=request.validity.expires_at,
            idempotency_key=idempotency_key,
            record_identity=identity,
            canonical_payload=json.loads(canonical),
        )
        won = self._insert(row, identity, self._existing_request, request.owner_id, idempotency_key)
        return self._request_to_domain(won)

    def get_approval_request(self, *, owner_id: str, request_id: str) -> ApprovalRequest | None:
        row = self._existing_request_by_id(owner_id, request_id)
        return None if row is None else self._request_to_domain(row)

    def read_approval_request_for_update(
        self, *, owner_id: str, request_id: str
    ) -> ApprovalRequest | None:
        """Read one request while holding its PostgreSQL row lock when supported.

        U7.2 uses this narrow persistence primitive to serialize one terminal
        decision per request. SQLite accepts the same statement as its local
        test/store behavior without claiming PostgreSQL row-lock semantics.
        """

        row = self._s.scalar(
            select(AuthorityApprovalRequestRow)
            .where(
                AuthorityApprovalRequestRow.owner_id == owner_id,
                AuthorityApprovalRequestRow.id == request_id,
            )
            .with_for_update()
        )
        return None if row is None else self._request_to_domain(row)

    def list_approval_requests(self, *, owner_id: str) -> tuple[ApprovalRequest, ...]:
        rows = self._s.scalars(
            select(AuthorityApprovalRequestRow)
            .where(AuthorityApprovalRequestRow.owner_id == owner_id)
            .order_by(AuthorityApprovalRequestRow.requested_at, AuthorityApprovalRequestRow.id)
        ).all()
        return tuple(self._request_to_domain(row) for row in rows)

    # -- approval decisions --------------------------------------------------

    def append_approval_decision(
        self, decision: ApprovalDecision, *, idempotency_key: str
    ) -> ApprovalDecision:
        canonical = canonical_authority_json(decision)
        identity = _identity(_DECISION_IDENTITY, canonical)
        resolved = self._resolve_replay(
            self._existing_decision(decision.owner_id, idempotency_key),
            self._existing_decision_by_id(decision.owner_id, decision.decision_id),
            identity,
        )
        if resolved is not None:
            return self._decision_to_domain(resolved)
        request_row = self._existing_request_by_id(decision.owner_id, decision.request_id)
        if request_row is None:
            raise AuthorityCausalityError("approval decision references a missing request")
        request = self._request_to_domain(request_row)
        if (
            decision.subject != request.subject
            or decision.capability != request.capability
            or decision.scope != request.scope
            or decision.purpose != request.purpose
            or decision.policy_version != request.policy_version
            or decision.validity != request.validity
        ):
            raise AuthorityCausalityError("approval decision does not echo its request")
        row = AuthorityApprovalDecisionRow(
            id=decision.decision_id,
            owner_id=decision.owner_id,
            schema_version=decision.schema_version,
            request_id=decision.request_id,
            decided_by=decision.decided_by.subject_id,
            outcome=decision.outcome.value,
            decided_at=decision.decided_at,
            capability=decision.capability,
            policy_version=decision.policy_version,
            idempotency_key=idempotency_key,
            record_identity=identity,
            canonical_payload=json.loads(canonical),
        )
        won = self._insert(
            row, identity, self._existing_decision, decision.owner_id, idempotency_key
        )
        return self._decision_to_domain(won)

    def get_approval_decision(self, *, owner_id: str, decision_id: str) -> ApprovalDecision | None:
        row = self._existing_decision_by_id(owner_id, decision_id)
        return None if row is None else self._decision_to_domain(row)

    def list_approval_decisions(self, *, owner_id: str) -> tuple[ApprovalDecision, ...]:
        rows = self._s.scalars(
            select(AuthorityApprovalDecisionRow)
            .where(AuthorityApprovalDecisionRow.owner_id == owner_id)
            .order_by(AuthorityApprovalDecisionRow.decided_at, AuthorityApprovalDecisionRow.id)
        ).all()
        return tuple(self._decision_to_domain(row) for row in rows)

    # -- capability grants ---------------------------------------------------

    def append_capability_grant(
        self, grant: CapabilityGrant, *, idempotency_key: str
    ) -> CapabilityGrant:
        canonical = canonical_authority_json(grant)
        identity = _identity(_GRANT_IDENTITY, canonical)
        resolved = self._resolve_replay(
            self._existing_grant(grant.owner_id, idempotency_key),
            self._existing_grant_by_id(grant.owner_id, grant.grant_id),
            identity,
        )
        if resolved is not None:
            return self._grant_to_domain(resolved)
        decision_row = self._existing_decision_by_id(grant.owner_id, grant.decision_id)
        if decision_row is None:
            raise AuthorityCausalityError("grant references a missing decision")
        decision = self._decision_to_domain(decision_row)
        if decision.request_id != grant.request_id:
            raise AuthorityCausalityError("grant and decision reference different requests")
        if decision.outcome is not ApprovalDecisionOutcome.APPROVED:
            raise AuthorityCausalityError("grant cannot be issued from a non-approved decision")
        if (
            grant.subject != decision.subject
            or grant.capability != decision.capability
            or grant.scope != decision.scope
            or grant.purpose != decision.purpose
            or grant.policy_version != decision.policy_version
            or grant.validity != decision.validity
        ):
            raise AuthorityCausalityError("grant does not match the approved decision")
        row = AuthorityCapabilityGrantRow(
            id=grant.grant_id,
            owner_id=grant.owner_id,
            schema_version=grant.schema_version,
            request_id=grant.request_id,
            decision_id=grant.decision_id,
            issued_by=grant.issued_by.subject_id,
            issued_at=grant.issued_at,
            subject_type=grant.subject.subject_type.value,
            subject_id=grant.subject.subject_id,
            capability=grant.capability,
            policy_version=grant.policy_version,
            valid_from=grant.validity.valid_from,
            expires_at=grant.validity.expires_at,
            delegation=grant.delegation.value,
            idempotency_key=idempotency_key,
            record_identity=identity,
            canonical_payload=json.loads(canonical),
        )
        won = self._insert(row, identity, self._existing_grant, grant.owner_id, idempotency_key)
        return self._grant_to_domain(won)

    def get_capability_grant(self, *, owner_id: str, grant_id: str) -> CapabilityGrant | None:
        row = self._existing_grant_by_id(owner_id, grant_id)
        return None if row is None else self._grant_to_domain(row)

    def list_capability_grants(self, *, owner_id: str) -> tuple[CapabilityGrant, ...]:
        rows = self._s.scalars(
            select(AuthorityCapabilityGrantRow)
            .where(AuthorityCapabilityGrantRow.owner_id == owner_id)
            .order_by(AuthorityCapabilityGrantRow.issued_at, AuthorityCapabilityGrantRow.id)
        ).all()
        return tuple(self._grant_to_domain(row) for row in rows)

    # -- revocations ---------------------------------------------------------

    def append_revocation(
        self, revocation: RevocationRecord, *, idempotency_key: str
    ) -> RevocationRecord:
        canonical = canonical_authority_json(revocation)
        identity = _identity(_REVOCATION_IDENTITY, canonical)
        resolved = self._resolve_replay(
            self._existing_revocation(revocation.owner_id, idempotency_key),
            self._existing_revocation_by_id(revocation.owner_id, revocation.revocation_id),
            identity,
        )
        if resolved is not None:
            return self._revocation_to_domain(resolved)
        self._lock_owner_grant_for_authority_append(revocation.owner_id, revocation.grant_id)
        row = AuthorityRevocationRow(
            id=revocation.revocation_id,
            owner_id=revocation.owner_id,
            schema_version=revocation.schema_version,
            grant_id=revocation.grant_id,
            revoked_by=revocation.revoked_by,
            effective_at=revocation.effective_at,
            recorded_at=revocation.recorded_at,
            idempotency_key=idempotency_key,
            record_identity=identity,
            canonical_payload=json.loads(canonical),
        )
        won = self._insert(
            row, identity, self._existing_revocation, revocation.owner_id, idempotency_key
        )
        return self._revocation_to_domain(won)

    def list_revocations_for_grant(
        self, *, owner_id: str, grant_id: str
    ) -> tuple[RevocationRecord, ...]:
        rows = self._s.scalars(
            select(AuthorityRevocationRow)
            .where(
                AuthorityRevocationRow.owner_id == owner_id,
                AuthorityRevocationRow.grant_id == grant_id,
            )
            .order_by(AuthorityRevocationRow.effective_at, AuthorityRevocationRow.id)
        ).all()
        return tuple(self._revocation_to_domain(row) for row in rows)

    def list_revocations_for_grant_bounded(
        self, *, owner_id: str, grant_id: str, limit: int
    ) -> tuple[RevocationRecord, ...]:
        """Same-owner revocations for one exact grant, with a database limit."""

        rows = self._s.scalars(
            select(AuthorityRevocationRow)
            .where(
                AuthorityRevocationRow.owner_id == owner_id,
                AuthorityRevocationRow.grant_id == grant_id,
            )
            .order_by(AuthorityRevocationRow.effective_at, AuthorityRevocationRow.id)
            .limit(limit)
        ).all()
        return tuple(self._revocation_to_domain(row) for row in rows)

    def read_revocation_count_for_grant(self, *, owner_id: str, grant_id: str) -> int:
        """Return the exact same-owner revocation count without materializing rows."""

        count = self._s.scalar(
            select(func.count())
            .select_from(AuthorityRevocationRow)
            .where(
                AuthorityRevocationRow.owner_id == owner_id,
                AuthorityRevocationRow.grant_id == grant_id,
            )
        )
        return int(count or 0)

    def read_revocation_for_grant(
        self, *, owner_id: str, grant_id: str, revocation_id: str
    ) -> RevocationRecord | None:
        """Read one exact owner- and grant-scoped revocation by its public id."""

        row = self._s.scalars(
            select(AuthorityRevocationRow).where(
                AuthorityRevocationRow.owner_id == owner_id,
                AuthorityRevocationRow.grant_id == grant_id,
                AuthorityRevocationRow.id == revocation_id,
            )
        ).one_or_none()
        return self._revocation_to_domain(row) if row is not None else None

    # -- authority evaluation records ----------------------------------------

    def append_evaluation_record(
        self,
        evaluation_request: AuthorityEvaluationRequest,
        decision: AuthorityEvaluationDecision,
        *,
        idempotency_key: str,
    ) -> AuthorityEvaluationDecision:
        identity = self._evaluation_identity(evaluation_request, decision)
        resolved = self._resolve_replay(
            self._existing_evaluation(evaluation_request.owner_id, idempotency_key),
            self._existing_evaluation_by_id(
                evaluation_request.owner_id, evaluation_request.evaluation_id
            ),
            identity,
        )
        if resolved is not None:
            return self._evaluation_to_domain(resolved)
        locked_grant_row = self._lock_owner_grant_for_authority_append(
            evaluation_request.owner_id, evaluation_request.grant.grant_id
        )
        if decision.evaluation_id != evaluation_request.evaluation_id:
            raise AuthorityCausalityError("evaluation decision does not match its request")
        if decision.evaluation_time != evaluation_request.evaluation_time:
            raise AuthorityCausalityError("evaluation decision time does not match its request")
        authoritative_request = self._authoritative_evaluation_request(
            evaluation_request, locked_grant_row
        )
        authoritative_decision = evaluate_authority(authoritative_request)
        if decision != authoritative_decision:
            raise AuthorityCausalityError("evaluation decision does not match persisted authority")
        row = AuthorityEvaluationRow(
            id=authoritative_request.evaluation_id,
            owner_id=authoritative_request.owner_id,
            schema_version=authoritative_decision.schema_version,
            grant_id=authoritative_request.grant.grant_id,
            request_id=authoritative_request.approval_request.request_id,
            decision_id=authoritative_request.approval_decision.decision_id,
            evaluation_time=authoritative_request.evaluation_time,
            capability=authoritative_request.capability,
            policy_version=authoritative_request.policy_version,
            allowed=authoritative_decision.authorized,
            reason_code=authoritative_decision.reason_code.value,
            relevant_revocation_id=_relevant_revocation_id(
                authoritative_request, authoritative_decision
            ),
            idempotency_key=idempotency_key,
            record_identity=identity,
            request_payload=json.loads(canonical_authority_json(authoritative_request)),
            decision_payload=json.loads(canonical_authority_json(authoritative_decision)),
        )
        won = self._insert(
            row,
            identity,
            self._existing_evaluation,
            authoritative_request.owner_id,
            idempotency_key,
        )
        return self._evaluation_to_domain(won)

    def list_evaluations(
        self, *, owner_id: str, grant_id: str
    ) -> tuple[AuthorityEvaluationDecision, ...]:
        rows = self._s.scalars(
            select(AuthorityEvaluationRow)
            .where(AuthorityEvaluationRow.owner_id == owner_id)
            .order_by(AuthorityEvaluationRow.evaluation_time, AuthorityEvaluationRow.id)
        ).all()
        decisions = tuple(self._evaluation_to_domain(row) for row in rows)
        return tuple(decision for decision in decisions if decision.grant_id == grant_id)

    # -- U7.3 bounded database-side reads (no migration; no new index) -------
    # These narrow methods exist so the operator API/Workbench never performs
    # unbounded owner-wide scans. Each applies an exact same-owner filter in the
    # database and a hard LIMIT, preserving the existing ORDER BY determinism and
    # the fail-closed row-to-domain re-parse. They do not change U7.1 semantics.

    def list_decisions_for_request(
        self, *, owner_id: str, request_id: str, limit: int
    ) -> tuple[ApprovalDecision, ...]:
        """Same-owner decisions for one exact request, bounded by ``limit``."""

        rows = self._s.scalars(
            select(AuthorityApprovalDecisionRow)
            .where(
                AuthorityApprovalDecisionRow.owner_id == owner_id,
                AuthorityApprovalDecisionRow.request_id == request_id,
            )
            .order_by(AuthorityApprovalDecisionRow.decided_at, AuthorityApprovalDecisionRow.id)
            .limit(limit)
        ).all()
        return tuple(self._decision_to_domain(row) for row in rows)

    def list_grants_for_request(
        self, *, owner_id: str, request_id: str, limit: int
    ) -> tuple[CapabilityGrant, ...]:
        """Same-owner grants for one exact request, bounded by ``limit``."""

        rows = self._s.scalars(
            select(AuthorityCapabilityGrantRow)
            .where(
                AuthorityCapabilityGrantRow.owner_id == owner_id,
                AuthorityCapabilityGrantRow.request_id == request_id,
            )
            .order_by(AuthorityCapabilityGrantRow.issued_at, AuthorityCapabilityGrantRow.id)
            .limit(limit)
        ).all()
        return tuple(self._grant_to_domain(row) for row in rows)

    def list_evaluations_for_grant_bounded(
        self, *, owner_id: str, grant_id: str, limit: int
    ) -> tuple[AuthorityEvaluationDecision, ...]:
        """Same-owner evaluations for one exact grant, bounded by ``limit``.

        This is the bounded variant of :meth:`list_evaluations`: it filters by
        ``grant_id`` in the database rather than in Python. The legacy
        Python-filtered method is preserved unchanged for existing callers.
        """

        rows = self._s.scalars(
            select(AuthorityEvaluationRow)
            .where(
                AuthorityEvaluationRow.owner_id == owner_id,
                AuthorityEvaluationRow.grant_id == grant_id,
            )
            .order_by(AuthorityEvaluationRow.evaluation_time, AuthorityEvaluationRow.id)
            .limit(limit)
        ).all()
        return tuple(self._evaluation_to_domain(row) for row in rows)

    def read_latest_evaluation_for_grant(
        self, *, owner_id: str, grant_id: str
    ) -> AuthorityEvaluationDecision | None:
        """Read one exact grant's latest evaluation without an older-page projection."""

        row = self._s.scalars(
            select(AuthorityEvaluationRow)
            .where(
                AuthorityEvaluationRow.owner_id == owner_id,
                AuthorityEvaluationRow.grant_id == grant_id,
            )
            .order_by(
                AuthorityEvaluationRow.evaluation_time.desc(), AuthorityEvaluationRow.id.desc()
            )
            .limit(1)
        ).first()
        return self._evaluation_to_domain(row) if row is not None else None

    def read_evaluation_for_grant(
        self, *, owner_id: str, grant_id: str, evaluation_id: str
    ) -> AuthorityEvaluationDecision | None:
        """Read one exact owner- and grant-scoped evaluation by its public id."""

        row = self._s.scalars(
            select(AuthorityEvaluationRow).where(
                AuthorityEvaluationRow.owner_id == owner_id,
                AuthorityEvaluationRow.grant_id == grant_id,
                AuthorityEvaluationRow.id == evaluation_id,
            )
        ).one_or_none()
        return self._evaluation_to_domain(row) if row is not None else None

    def list_approval_requests_bounded(
        self, *, owner_id: str, limit: int
    ) -> tuple[ApprovalRequest, ...]:
        """Bounded same-owner approval-request list (page size capped in the DB)."""

        rows = self._s.scalars(
            select(AuthorityApprovalRequestRow)
            .where(AuthorityApprovalRequestRow.owner_id == owner_id)
            .order_by(AuthorityApprovalRequestRow.requested_at, AuthorityApprovalRequestRow.id)
            .limit(limit)
        ).all()
        return tuple(self._request_to_domain(row) for row in rows)

    def list_capability_grants_bounded(
        self, *, owner_id: str, limit: int
    ) -> tuple[CapabilityGrant, ...]:
        """Bounded same-owner grant list (page size capped in the DB)."""

        rows = self._s.scalars(
            select(AuthorityCapabilityGrantRow)
            .where(AuthorityCapabilityGrantRow.owner_id == owner_id)
            .order_by(AuthorityCapabilityGrantRow.issued_at, AuthorityCapabilityGrantRow.id)
            .limit(limit)
        ).all()
        return tuple(self._grant_to_domain(row) for row in rows)

    def read_authority_chain(
        self, *, owner_id: str, grant_id: str
    ) -> AuthorityChainProjection | None:
        """Owner-scoped, read-only persistence projection of one grant's chain.

        A pure read that assembles existing records; it computes no lifecycle
        decision and issues nothing (U7.2 owns lifecycle logic).
        """
        grant_row = self._existing_grant_by_id(owner_id, grant_id)
        if grant_row is None:
            return None
        grant = self._grant_to_domain(grant_row)
        decision_row = self._existing_decision_by_id(owner_id, grant.decision_id)
        request_row = self._existing_request_by_id(owner_id, grant.request_id)
        return AuthorityChainProjection(
            approval_request=(
                None if request_row is None else self._request_to_domain(request_row)
            ),
            approval_decision=(
                None if decision_row is None else self._decision_to_domain(decision_row)
            ),
            grant=grant,
            revocations=self.list_revocations_for_grant(owner_id=owner_id, grant_id=grant_id),
            evaluations=self.list_evaluations(owner_id=owner_id, grant_id=grant_id),
        )

    def _authoritative_evaluation_request(
        self, supplied: AuthorityEvaluationRequest, locked_grant_row: AuthorityCapabilityGrantRow
    ) -> AuthorityEvaluationRequest:
        """Rebuild an evaluation request from complete owner-scoped stored truth."""
        chain = self._resolve_persisted_evaluation_chain(supplied, locked_grant_row)
        return AuthorityEvaluationRequest(
            evaluation_id=supplied.evaluation_id,
            owner_id=supplied.owner_id,
            evaluation_time=supplied.evaluation_time,
            subject=supplied.subject,
            capability=supplied.capability,
            scope=supplied.scope,
            purpose=supplied.purpose,
            policy_version=supplied.policy_version,
            delegation_requested=supplied.delegation_requested,
            approval_request=chain.approval_request,
            approval_decision=chain.approval_decision,
            grant=chain.grant,
            revocations=chain.revocations,
        )

    def _resolve_persisted_evaluation_chain(
        self, supplied: AuthorityEvaluationRequest, locked_grant_row: AuthorityCapabilityGrantRow
    ) -> _PersistedEvaluationChain:
        """Load and validate the complete stored same-owner authority chain."""
        owner_id = supplied.owner_id
        request_row = self._existing_request_by_id(owner_id, supplied.approval_request.request_id)
        decision_row = self._existing_decision_by_id(
            owner_id, supplied.approval_decision.decision_id
        )
        if locked_grant_row.owner_id != owner_id or locked_grant_row.id != supplied.grant.grant_id:
            raise AuthorityCausalityError("evaluation authority chain is not available")
        if request_row is None or decision_row is None:
            raise AuthorityCausalityError("evaluation authority chain is not available")

        chain = _PersistedEvaluationChain(
            approval_request=self._request_to_domain(request_row),
            approval_decision=self._decision_to_domain(decision_row),
            grant=self._grant_to_domain(locked_grant_row),
            revocations=self._bounded_revocations_for_evaluation(owner_id, locked_grant_row.id),
        )
        if (
            supplied.approval_request != chain.approval_request
            or supplied.approval_decision != chain.approval_decision
            or supplied.grant != chain.grant
            or supplied.revocations != chain.revocations
        ):
            raise AuthorityCausalityError(
                "evaluation authority chain does not match persisted truth"
            )
        if not _is_complete_persisted_evaluation_chain(owner_id, chain):
            raise AuthorityCausalityError("evaluation authority chain is inconsistent")
        return chain

    def _bounded_revocations_for_evaluation(
        self, owner_id: str, grant_id: str
    ) -> tuple[RevocationRecord, ...]:
        """Load complete exact-grant revocation truth or fail closed at the fixed bound."""

        rows = self.list_revocations_for_grant_bounded(
            owner_id=owner_id, grant_id=grant_id, limit=51
        )
        if len(rows) > 50:
            raise AuthorityCausalityError("authority grant has too many revocations to evaluate")
        return rows

    # -- idempotency + insert ------------------------------------------------

    @staticmethod
    def _resolve_replay[RowT: _IdempotentRow](
        existing_by_key: RowT | None, existing_by_id: RowT | None, identity: str
    ) -> RowT | None:
        """Deterministic replay resolution (no DB constraint reliance).

        A matching key- or id-record with an identical identity is an
        idempotent replay; a same key or same id with a different identity is a
        fail-closed conflict. Detecting both here means duplicates never reach a
        database constraint, so a single SQLite transaction is never poisoned.
        """
        for existing in (existing_by_key, existing_by_id):
            if existing is not None:
                if existing.record_identity != identity:
                    raise IdempotencyConflictError(
                        "authority idempotency key or record id reused with a different payload"
                    )
                return existing
        return None

    def _insert[RowT: _IdempotentRow](
        self,
        row: RowT,
        identity: str,
        finder: Callable[[str, str], RowT | None],
        owner_id: str,
        idempotency_key: str,
    ) -> RowT:
        if not self._use_savepoint:
            self._s.add(row)
            self._s.flush()
            return row
        try:
            with self._s.begin_nested():
                self._s.add(row)
                self._s.flush()
        except IntegrityError as error:
            self._s.expire_all()
            won = finder(owner_id, idempotency_key)
            if won is not None and won.record_identity == identity:
                return won
            raise IdempotencyConflictError(
                "authority record conflicts with an existing record"
            ) from error
        return row

    @staticmethod
    def _evaluation_identity(
        evaluation_request: AuthorityEvaluationRequest, decision: AuthorityEvaluationDecision
    ) -> str:
        request_canonical = canonical_authority_json(evaluation_request)
        decision_canonical = canonical_authority_json(decision)
        return _identity(
            _EVALUATION_IDENTITY, request_canonical + _PAYLOAD_SEP + decision_canonical
        )

    # -- internal owner-scoped queries --------------------------------------

    def _lock_owner_grant_for_authority_append(
        self, owner_id: str, grant_id: str
    ) -> AuthorityCapabilityGrantRow:
        """Lock one exact grant through an authority append transaction.

        PostgreSQL uses this row lock as the serialization point shared by
        revocation and evaluation appends. SQLite keeps its established local
        behavior without claiming PostgreSQL row-lock semantics.
        """
        statement = select(AuthorityCapabilityGrantRow).where(
            AuthorityCapabilityGrantRow.owner_id == owner_id,
            AuthorityCapabilityGrantRow.id == grant_id,
        )
        if self._s.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update()
        row = self._s.scalars(statement).one_or_none()
        if row is None:
            raise AuthorityCausalityError("authority append references a missing grant")
        return row

    def _existing_request(
        self, owner_id: str, idempotency_key: str
    ) -> AuthorityApprovalRequestRow | None:
        return self._s.scalars(
            select(AuthorityApprovalRequestRow).where(
                AuthorityApprovalRequestRow.owner_id == owner_id,
                AuthorityApprovalRequestRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()

    def _existing_request_by_id(
        self, owner_id: str, request_id: str
    ) -> AuthorityApprovalRequestRow | None:
        return self._s.scalars(
            select(AuthorityApprovalRequestRow).where(
                AuthorityApprovalRequestRow.owner_id == owner_id,
                AuthorityApprovalRequestRow.id == request_id,
            )
        ).one_or_none()

    def _existing_decision(
        self, owner_id: str, idempotency_key: str
    ) -> AuthorityApprovalDecisionRow | None:
        return self._s.scalars(
            select(AuthorityApprovalDecisionRow).where(
                AuthorityApprovalDecisionRow.owner_id == owner_id,
                AuthorityApprovalDecisionRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()

    def _existing_decision_by_id(
        self, owner_id: str, decision_id: str
    ) -> AuthorityApprovalDecisionRow | None:
        return self._s.scalars(
            select(AuthorityApprovalDecisionRow).where(
                AuthorityApprovalDecisionRow.owner_id == owner_id,
                AuthorityApprovalDecisionRow.id == decision_id,
            )
        ).one_or_none()

    def _existing_grant(
        self, owner_id: str, idempotency_key: str
    ) -> AuthorityCapabilityGrantRow | None:
        return self._s.scalars(
            select(AuthorityCapabilityGrantRow).where(
                AuthorityCapabilityGrantRow.owner_id == owner_id,
                AuthorityCapabilityGrantRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()

    def _existing_grant_by_id(
        self, owner_id: str, grant_id: str
    ) -> AuthorityCapabilityGrantRow | None:
        return self._s.scalars(
            select(AuthorityCapabilityGrantRow).where(
                AuthorityCapabilityGrantRow.owner_id == owner_id,
                AuthorityCapabilityGrantRow.id == grant_id,
            )
        ).one_or_none()

    def _existing_revocation(
        self, owner_id: str, idempotency_key: str
    ) -> AuthorityRevocationRow | None:
        return self._s.scalars(
            select(AuthorityRevocationRow).where(
                AuthorityRevocationRow.owner_id == owner_id,
                AuthorityRevocationRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()

    def _existing_revocation_by_id(
        self, owner_id: str, revocation_id: str
    ) -> AuthorityRevocationRow | None:
        return self._s.scalars(
            select(AuthorityRevocationRow).where(
                AuthorityRevocationRow.owner_id == owner_id,
                AuthorityRevocationRow.id == revocation_id,
            )
        ).one_or_none()

    def _existing_evaluation(
        self, owner_id: str, idempotency_key: str
    ) -> AuthorityEvaluationRow | None:
        return self._s.scalars(
            select(AuthorityEvaluationRow).where(
                AuthorityEvaluationRow.owner_id == owner_id,
                AuthorityEvaluationRow.idempotency_key == idempotency_key,
            )
        ).one_or_none()

    def _existing_evaluation_by_id(
        self, owner_id: str, evaluation_id: str
    ) -> AuthorityEvaluationRow | None:
        return self._s.scalars(
            select(AuthorityEvaluationRow).where(
                AuthorityEvaluationRow.owner_id == owner_id,
                AuthorityEvaluationRow.id == evaluation_id,
            )
        ).one_or_none()

    # -- row-to-domain (fail-closed) ----------------------------------------

    def _request_to_domain(self, row: AuthorityApprovalRequestRow) -> ApprovalRequest:
        return _parse(
            ApprovalRequest, row.canonical_payload, row.record_identity, _REQUEST_IDENTITY
        )

    def _decision_to_domain(self, row: AuthorityApprovalDecisionRow) -> ApprovalDecision:
        return _parse(
            ApprovalDecision, row.canonical_payload, row.record_identity, _DECISION_IDENTITY
        )

    def _grant_to_domain(self, row: AuthorityCapabilityGrantRow) -> CapabilityGrant:
        return _parse(CapabilityGrant, row.canonical_payload, row.record_identity, _GRANT_IDENTITY)

    def _revocation_to_domain(self, row: AuthorityRevocationRow) -> RevocationRecord:
        return _parse(
            RevocationRecord, row.canonical_payload, row.record_identity, _REVOCATION_IDENTITY
        )

    def _evaluation_to_domain(self, row: AuthorityEvaluationRow) -> AuthorityEvaluationDecision:
        decision = _parse_no_identity(AuthorityEvaluationDecision, row.decision_payload)
        request = _parse_no_identity(AuthorityEvaluationRequest, row.request_payload)
        recomputed = self._evaluation_identity(request, decision)
        if recomputed != row.record_identity:
            raise AuthorityRecordCorruptError("stored authority evaluation identity mismatch")
        if evaluate_authority(request) != decision:
            raise AuthorityRecordCorruptError("stored authority evaluation is not deterministic")
        self._verify_evaluation_projections(row, request, decision)
        return decision

    @staticmethod
    def _verify_evaluation_projections(
        row: AuthorityEvaluationRow,
        request: AuthorityEvaluationRequest,
        decision: AuthorityEvaluationDecision,
    ) -> None:
        """Reject any scalar projection that diverges from canonical payload truth."""
        try:
            stored_evaluation_time = ensure_utc(row.evaluation_time)
        except ValueError as error:
            raise AuthorityRecordCorruptError(
                "stored authority evaluation projection mismatch"
            ) from error
        if (
            row.id != request.evaluation_id
            or decision.evaluation_id != request.evaluation_id
            or row.owner_id != request.owner_id
            or row.schema_version != decision.schema_version
            or row.schema_version != request.schema_version
            or row.grant_id != request.grant.grant_id
            or row.grant_id != decision.grant_id
            or row.request_id != request.approval_request.request_id
            or row.decision_id != request.approval_decision.decision_id
            or stored_evaluation_time != ensure_utc(request.evaluation_time)
            or stored_evaluation_time != ensure_utc(decision.evaluation_time)
            or row.capability != request.capability
            or row.policy_version != request.policy_version
            or row.allowed != decision.authorized
            or row.reason_code != decision.reason_code.value
            or row.relevant_revocation_id != _relevant_revocation_id(request, decision)
        ):
            raise AuthorityRecordCorruptError("stored authority evaluation projection mismatch")


def _relevant_revocation_id(
    evaluation_request: AuthorityEvaluationRequest, decision: AuthorityEvaluationDecision
) -> str | None:
    if decision.reason_code is not AuthorityReasonCode.REVOKED:
        return None
    for revocation in evaluation_request.revocations:  # already earliest-first
        if evaluation_request.evaluation_time >= revocation.effective_at:
            return revocation.revocation_id
    return None


def _is_complete_persisted_evaluation_chain(
    owner_id: str, chain: _PersistedEvaluationChain
) -> bool:
    """Confirm the stored request, decision, and grant form one exact chain."""
    request = chain.approval_request
    decision = chain.approval_decision
    grant = chain.grant
    if {owner_id, request.owner_id, decision.owner_id, grant.owner_id} != {owner_id}:
        return False
    if (
        decision.request_id != request.request_id
        or grant.request_id != request.request_id
        or grant.decision_id != decision.decision_id
        or decision.outcome is not ApprovalDecisionOutcome.APPROVED
    ):
        return False
    if (
        decision.subject != request.subject
        or decision.capability != request.capability
        or decision.scope != request.scope
        or decision.purpose != request.purpose
        or decision.policy_version != request.policy_version
        or decision.validity != request.validity
    ):
        return False
    if (
        grant.subject != decision.subject
        or grant.capability != decision.capability
        or grant.scope != decision.scope
        or grant.purpose != decision.purpose
        or grant.policy_version != decision.policy_version
        or grant.validity != decision.validity
    ):
        return False
    return all(
        revocation.owner_id == owner_id and revocation.grant_id == grant.grant_id
        for revocation in chain.revocations
    )


def _parse[ModelT: BaseModel](
    model_type: type[ModelT],
    payload: dict[str, object],
    stored_identity: str,
    domain_separator: bytes,
) -> ModelT:
    model = _parse_no_identity(model_type, payload)
    recomputed = _identity(domain_separator, canonical_authority_json(model))
    if recomputed != stored_identity:
        raise AuthorityRecordCorruptError(
            f"stored authority record identity mismatch for {model_type.__name__}"
        )
    return model


def _parse_no_identity[ModelT: BaseModel](
    model_type: type[ModelT], payload: dict[str, object]
) -> ModelT:
    try:
        return parse_authority_json(model_type, json.dumps(payload))
    except ValidationError as error:
        raise AuthorityRecordCorruptError(
            f"stored authority record failed re-parsing for {model_type.__name__}"
        ) from error
