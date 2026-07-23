"""Owner-scoped, append-only repository for gateway governance evidence."""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.core.checksums import sha256_bytes
from orbitmind.core.errors import IdempotencyConflictError, ValidationError
from orbitmind.persistence.tool_gateway_models import OperationToolGatewayDecisionRow
from orbitmind.toolgateway.contracts import (
    GatewayDecisionRecord,
    parse_tool_gateway_json,
    tool_gateway_canonical_json,
)

_IDENTITY = b"orbitmind-tool-gateway-decision-record-identity-v1\x00"


class GatewayDisposition(StrEnum):
    CREATED = "created"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True)
class GatewayWriteResult:
    record: GatewayDecisionRecord
    disposition: GatewayDisposition


class GatewayDecisionCorruptError(ValidationError):
    code = "gateway_decision_corrupt"


def _identity(canonical: str) -> str:
    return sha256_bytes(_IDENTITY + canonical.encode())


class SqlAlchemyToolGatewayRepository:
    def __init__(self, session: Session) -> None:
        self._s = session
        self._use_savepoint = session.get_bind().dialect.name != "sqlite"

    def _by_key(self, owner_id: str, key: str) -> OperationToolGatewayDecisionRow | None:
        return self._s.scalar(
            select(OperationToolGatewayDecisionRow).where(
                OperationToolGatewayDecisionRow.owner_id == owner_id,
                OperationToolGatewayDecisionRow.idempotency_key == key,
            )
        )

    def _by_id(self, owner_id: str, record_id: str) -> OperationToolGatewayDecisionRow | None:
        return self._s.scalar(
            select(OperationToolGatewayDecisionRow).where(
                OperationToolGatewayDecisionRow.owner_id == owner_id,
                OperationToolGatewayDecisionRow.gateway_decision_id == record_id,
            )
        )

    def resolve_historical_replay(
        self, *, owner_id: str, idempotency_key: str, proposal_fingerprint: str
    ) -> GatewayDecisionRecord | None:
        row = self._by_key(owner_id, idempotency_key)
        if row is None:
            return None
        if row.proposal_fingerprint != proposal_fingerprint:
            raise IdempotencyConflictError(
                "gateway idempotency key was reused for a different proposal"
            )
        return self._to_domain(row)

    def append_gateway_decision_record(
        self, record: GatewayDecisionRecord, *, idempotency_key: str
    ) -> GatewayWriteResult:
        existing = self._by_key(record.owner_id, idempotency_key) or self._by_id(
            record.owner_id, record.gateway_decision_id
        )
        if existing is not None:
            if existing.proposal_fingerprint != record.proposal_fingerprint:
                raise IdempotencyConflictError(
                    "gateway decision identity was reused for a different proposal"
                )
            return GatewayWriteResult(self._to_domain(existing), GatewayDisposition.REPLAYED)
        canonical = tool_gateway_canonical_json(record)
        row = OperationToolGatewayDecisionRow(
            gateway_decision_id=record.gateway_decision_id,
            owner_id=record.owner_id,
            schema_version=record.schema_version,
            proposal_id=record.proposal_id,
            actor_id=record.actor_id,
            tool_id=record.tool_id,
            tool_version=record.tool_version,
            descriptor_checksum=record.descriptor_checksum,
            referenced_admission_id=record.referenced_admission_id,
            resolved_admission_id=record.resolved_admission_id,
            admission_record_identity=record.admission_record_identity,
            outcome=record.outcome.value,
            primary_reason_code=record.primary_reason_code.value,
            policy_version=record.policy_version,
            evaluated_at=record.evaluated_at,
            requested_at=record.requested_at,
            proposal_fingerprint=record.proposal_fingerprint,
            decision_checksum=record.decision_checksum,
            record_identity=_identity(canonical),
            created_at=record.created_at,
            idempotency_key=idempotency_key,
            canonical_payload=json.loads(canonical),
        )
        if self._use_savepoint:
            try:
                with self._s.begin_nested():
                    self._s.add(row)
                    self._s.flush()
                return GatewayWriteResult(self._to_domain(row), GatewayDisposition.CREATED)
            except IntegrityError:
                replay = self._by_key(record.owner_id, idempotency_key) or self._by_id(
                    record.owner_id, record.gateway_decision_id
                )
                if (
                    replay is not None
                    and replay.proposal_fingerprint == record.proposal_fingerprint
                ):
                    return GatewayWriteResult(self._to_domain(replay), GatewayDisposition.REPLAYED)
                raise
        self._s.add(row)
        self._s.flush()
        return GatewayWriteResult(self._to_domain(row), GatewayDisposition.CREATED)

    def get_gateway_decision_record(
        self, *, owner_id: str, gateway_decision_id: str
    ) -> GatewayDecisionRecord | None:
        row = self._by_id(owner_id, gateway_decision_id)
        return None if row is None else self._to_domain(row)

    def list_gateway_decision_records_bounded(
        self, *, owner_id: str, limit: int
    ) -> tuple[GatewayDecisionRecord, ...]:
        rows = self._s.scalars(
            select(OperationToolGatewayDecisionRow)
            .where(OperationToolGatewayDecisionRow.owner_id == owner_id)
            .order_by(
                OperationToolGatewayDecisionRow.created_at,
                OperationToolGatewayDecisionRow.gateway_decision_id,
            )
            .limit(limit)
        ).all()
        return tuple(self._to_domain(row) for row in rows)

    def _to_domain(self, row: OperationToolGatewayDecisionRow) -> GatewayDecisionRecord:
        if not isinstance(row.canonical_payload, Mapping):
            raise GatewayDecisionCorruptError("stored gateway payload is not a mapping")
        canonical = json.dumps(
            row.canonical_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        if not hmac.compare_digest(_identity(canonical), row.record_identity):
            raise GatewayDecisionCorruptError("stored gateway record failed identity verification")
        try:
            parsed = parse_tool_gateway_json(GatewayDecisionRecord, canonical)
            if not isinstance(parsed, GatewayDecisionRecord):
                raise GatewayDecisionCorruptError(
                    "stored gateway record did not parse as decision evidence"
                )
            return parsed
        except ValidationError as error:
            raise GatewayDecisionCorruptError(
                "stored gateway record failed fail-closed re-parsing"
            ) from error
