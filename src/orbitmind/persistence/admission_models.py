"""SQLAlchemy row for durable Operation Admission v0 evidence (U7.4).

One append-only, owner-scoped, immutable admission record per decision. There is
no mutable-status column: the outcome and reason codes are fixed evidence of one
deterministic evaluation. No column stores a secret, credential, token, command,
import path, environment variable, filesystem path, or tool handle.

Design (mirrors the U7.1 authority tables):

- composite ``PrimaryKeyConstraint(admission_id, owner_id)`` so ids are unique
  *per owner* and cannot probe another owner's namespace;
- ``UniqueConstraint(owner_id, idempotency_key)`` for owner-scoped replay;
- a **nullable, owner-qualified** foreign key on ``resolved_authority_grant_id``
  (populated only when a real owner-scoped grant was resolved) with
  ``ondelete="RESTRICT"`` — evidence can never be erased by cascade — while the
  FK-free ``requested_authority_grant_id`` may hold an invalid/nonexistent id;
- ``canonical_payload`` holds the full canonical domain JSON and
  ``record_identity`` = domain-separated SHA-256 of that payload.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime

_SCHEMA = "operation-admission-v0"
_ID = 128
_OWNER = 120
_CAP = 64
_POLICY = 64
_IDEMPOTENCY = 200
_IDENTITY = 64
_HASH = 64


class OperationAdmissionRecordRow(Base):
    """One immutable owner-scoped admission decision record."""

    __tablename__ = "operation_admission_records"
    __table_args__ = (
        PrimaryKeyConstraint("admission_id", "owner_id", name="pk_admission_records_owner"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_admission_records_idempotency"),
        ForeignKeyConstraint(
            ["resolved_authority_grant_id", "owner_id"],
            ["authority_capability_grants.id", "authority_capability_grants.owner_id"],
            name="fk_admission_records_resolved_grant_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_admission_records_owner_created", "owner_id", "created_at"),
        CheckConstraint("length(owner_id) > 0", name="ck_admission_records_owner"),
        CheckConstraint(f"schema_version = '{_SCHEMA}'", name="ck_admission_records_schema"),
        CheckConstraint(
            f"length(record_identity) = {_IDENTITY}", name="ck_admission_records_identity"
        ),
        CheckConstraint(
            "outcome IN ('admitted', 'denied', 'approval_required')",
            name="ck_admission_records_outcome",
        ),
    )

    admission_id: Mapped[str] = mapped_column(String(_ID))
    owner_id: Mapped[str] = mapped_column(String(_OWNER))
    schema_version: Mapped[str] = mapped_column(String(48))
    proposal_id: Mapped[str] = mapped_column(String(_ID))
    actor_id: Mapped[str] = mapped_column(String(_ID))
    actor_type: Mapped[str] = mapped_column(String(32))
    operation_kind: Mapped[str] = mapped_column(String(_CAP))
    requested_capability: Mapped[str] = mapped_column(String(_CAP))
    side_effect_class: Mapped[str] = mapped_column(String(32))
    risk_class: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(32))
    primary_reason_code: Mapped[str] = mapped_column(String(48))
    policy_version: Mapped[str] = mapped_column(String(_POLICY))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    requested_authority_grant_id: Mapped[str | None] = mapped_column(String(_ID), nullable=True)
    resolved_authority_grant_id: Mapped[str | None] = mapped_column(String(_ID), nullable=True)
    proposal_fingerprint: Mapped[str] = mapped_column(String(_HASH))
    decision_checksum: Mapped[str] = mapped_column(String(_HASH))
    record_identity: Mapped[str] = mapped_column(String(_IDENTITY))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(_IDEMPOTENCY))
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSON)
