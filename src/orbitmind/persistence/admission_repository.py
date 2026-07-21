"""Append-only, owner-scoped persistence for Operation Admission v0 evidence (U7.4).

Stores immutable :class:`~orbitmind.admission.contracts.AdmissionRecord` evidence
and reads it back fail-closed. Exposes only ``append`` / ``get`` / ``list`` — there
is no update, delete, or execute operation.

Guarantees:

- **Owner scoping**: every read/write is owner-qualified.
- **Append-only**: no mutation of a stored record.
- **Idempotency**: an ``(owner_id, idempotency_key)`` replay with the same
  ``proposal_fingerprint`` returns the stored record; a different fingerprint
  fails closed with ``IdempotencyConflictError``. Replay returns historical
  evidence only — a record is not a bearer token or current execution authority.
- **Self-reference-free identity**: ``canonical_payload`` is the canonical
  serialization of the record (which contains neither ``record_identity`` nor
  ``canonical_payload``); ``record_identity`` is the domain-separated SHA-256 of
  exactly those canonical bytes.
- **Fail-closed reads**: row-to-domain re-parses the stored canonical payload
  through the frozen contract, so tampered/unknown data raises.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.admission.contracts import (
    AdmissionRecord,
    admission_canonical_json,
    parse_admission_json,
)
from orbitmind.core.checksums import sha256_bytes
from orbitmind.core.errors import IdempotencyConflictError, ValidationError
from orbitmind.persistence.admission_models import OperationAdmissionRecordRow

_ADMISSION_IDENTITY = b"orbitmind-operation-admission-record-identity-v1\x00"


class AdmissionRecordCorruptError(ValidationError):
    """A stored admission record failed fail-closed verification/re-parsing on read."""

    code = "admission_record_corrupt"


def _canonical_payload_bytes(payload: Mapping[str, object]) -> str:
    """Deterministic canonical serialization of a stored payload mapping.

    Uses exactly the parameters of ``admission_canonical_json`` (sorted keys,
    compact UTF-8), so re-canonicalizing a stored ``canonical_payload`` reproduces
    the same bytes that were hashed at write time — independent of the database's
    physical key ordering.
    """
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _identity(canonical_json: str) -> str:
    """The single shared record-identity: domain-separated SHA-256 of canonical bytes.

    Used by both the write path and the read-time integrity verification.
    """
    return sha256_bytes(_ADMISSION_IDENTITY + canonical_json.encode("utf-8"))


class SqlAlchemyAdmissionRepository:
    """Owner-scoped, append-only repository over one SQLAlchemy session."""

    def __init__(self, session: Session) -> None:
        self._s = session
        # pysqlite does not participate in SAVEPOINT-based outer rollback; disable
        # savepoints on SQLite (deterministic pre-checks cover replay) and keep
        # savepoint recovery on PostgreSQL — mirrors the authority repository.
        self._use_savepoint = session.get_bind().dialect.name != "sqlite"

    def append_admission_record(
        self, record: AdmissionRecord, *, idempotency_key: str
    ) -> AdmissionRecord:
        canonical = admission_canonical_json(record)
        identity = _identity(canonical)
        resolved = self._resolve_replay(
            self._by_idempotency(record.owner_id, idempotency_key),
            self._by_id(record.owner_id, record.admission_id),
            record.proposal_fingerprint,
        )
        if resolved is not None:
            return self._to_domain(resolved)
        row = OperationAdmissionRecordRow(
            admission_id=record.admission_id,
            owner_id=record.owner_id,
            schema_version=record.schema_version,
            proposal_id=record.proposal_id,
            actor_id=record.actor_id,
            actor_type=record.actor_type.value,
            operation_kind=record.operation_kind,
            requested_capability=record.requested_capability,
            side_effect_class=record.side_effect_class.value,
            risk_class=record.risk_class.value,
            outcome=record.outcome.value,
            primary_reason_code=record.primary_reason_code.value,
            policy_version=record.policy_version,
            evaluated_at=record.evaluated_at,
            requested_at=record.requested_at,
            requested_authority_grant_id=record.requested_authority_grant_id,
            resolved_authority_grant_id=record.resolved_authority_grant_id,
            proposal_fingerprint=record.proposal_fingerprint,
            decision_checksum=record.decision_checksum,
            record_identity=identity,
            created_at=record.created_at,
            idempotency_key=idempotency_key,
            canonical_payload=json.loads(canonical),
        )
        won = self._insert(row, record.owner_id, idempotency_key, record.proposal_fingerprint)
        return self._to_domain(won)

    def get_admission_record(self, *, owner_id: str, admission_id: str) -> AdmissionRecord | None:
        row = self._by_id(owner_id, admission_id)
        return None if row is None else self._to_domain(row)

    def list_admission_records(self, *, owner_id: str) -> tuple[AdmissionRecord, ...]:
        rows = self._s.scalars(
            select(OperationAdmissionRecordRow)
            .where(OperationAdmissionRecordRow.owner_id == owner_id)
            .order_by(
                OperationAdmissionRecordRow.created_at, OperationAdmissionRecordRow.admission_id
            )
        ).all()
        return tuple(self._to_domain(row) for row in rows)

    # -- internals -----------------------------------------------------------

    def _by_idempotency(
        self, owner_id: str, idempotency_key: str
    ) -> OperationAdmissionRecordRow | None:
        return self._s.scalar(
            select(OperationAdmissionRecordRow).where(
                OperationAdmissionRecordRow.owner_id == owner_id,
                OperationAdmissionRecordRow.idempotency_key == idempotency_key,
            )
        )

    def _by_id(self, owner_id: str, admission_id: str) -> OperationAdmissionRecordRow | None:
        return self._s.scalar(
            select(OperationAdmissionRecordRow).where(
                OperationAdmissionRecordRow.owner_id == owner_id,
                OperationAdmissionRecordRow.admission_id == admission_id,
            )
        )

    def _resolve_replay(
        self,
        by_key: OperationAdmissionRecordRow | None,
        by_id: OperationAdmissionRecordRow | None,
        proposal_fingerprint: str,
    ) -> OperationAdmissionRecordRow | None:
        if by_key is not None:
            if by_key.proposal_fingerprint == proposal_fingerprint:
                return by_key
            raise IdempotencyConflictError(
                "admission idempotency key was reused for a different proposal"
            )
        if by_id is not None:
            if by_id.proposal_fingerprint == proposal_fingerprint:
                return by_id
            raise IdempotencyConflictError("admission id was reused for a different proposal")
        return None

    def _insert(
        self,
        row: OperationAdmissionRecordRow,
        owner_id: str,
        idempotency_key: str,
        proposal_fingerprint: str,
    ) -> OperationAdmissionRecordRow:
        if self._use_savepoint:
            try:
                with self._s.begin_nested():
                    self._s.add(row)
                    self._s.flush()
                return row
            except IntegrityError:
                replayed = self._resolve_replay(
                    self._by_idempotency(owner_id, idempotency_key),
                    self._by_id(owner_id, row.admission_id),
                    proposal_fingerprint,
                )
                if replayed is not None:
                    return replayed
                raise
        self._s.add(row)
        self._s.flush()
        return row

    def _to_domain(self, row: OperationAdmissionRecordRow) -> AdmissionRecord:
        # 1: load the stored canonical payload; fail closed if it is not a bounded
        # mapping (it must never contain record_identity or canonical_payload itself).
        payload = row.canonical_payload
        if not isinstance(payload, Mapping):
            raise AdmissionRecordCorruptError("stored admission payload is not a bounded mapping")
        # 2: reproduce the exact canonical bytes and recompute the record identity
        # with the same shared helper used at write time.
        canonical = _canonical_payload_bytes(payload)
        recomputed = _identity(canonical)
        # 3: timing-safe comparison against the stored identity. On mismatch, fail
        # closed without revealing the altered payload and without repairing the row.
        if not hmac.compare_digest(recomputed, row.record_identity):
            raise AdmissionRecordCorruptError(
                "stored admission record failed identity verification"
            )
        # 4: only after identity is verified, re-parse fail-closed through the frozen contract.
        try:
            return parse_admission_json(AdmissionRecord, canonical)
        except ValidationError as error:
            raise AdmissionRecordCorruptError(
                "stored admission record failed fail-closed re-parsing"
            ) from error
