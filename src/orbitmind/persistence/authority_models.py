"""SQLAlchemy rows for durable U7 authority evidence (U7.1).

Append-only, owner-scoped persistence for the U7.0 authority contracts:
approval requests, approval decisions, capability grants, revocations, and
authority-evaluation records. Every row is immutable evidence — there are no
mutable-status columns, and status (expired/revoked) is never stored; it is
derived from the explicit timestamps and revocation evidence by U7.0
evaluation.

Design:

- Every table has a composite ``PrimaryKeyConstraint(id, owner_id)`` so ids are
  unique *per owner*: one owner can never collide with (or probe the existence
  of) another owner's identifiers, and owner-qualified foreign keys make
  cross-owner links impossible (defense in depth behind the repository's
  owner-scoped checks).
- Each row stores the exact scalar identities needed for owner-scoped reads,
  causality foreign keys, and uniqueness, plus a ``canonical_payload`` holding
  the full canonical domain JSON and a ``record_identity`` = domain-separated
  SHA-256 of that payload (identity, not signature). Row-to-domain re-parses
  the payload through the frozen U7.0 contract, so unknown enums, wrong types,
  or tampered data fail closed on read.
- No column stores a secret, credential, token, command, import path,
  environment variable, filesystem path, or tool handle.
- Foreign keys use ``ondelete="RESTRICT"``: authority evidence can never be
  erased by a cascade.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime

_SCHEMA = "authority-contracts-v1"
_ID = 128
_OWNER = 120
_CAP = 64
_POLICY = 64
_IDEMPOTENCY = 200
_IDENTITY = 64


def _schema_check(table: str) -> CheckConstraint:
    return CheckConstraint(f"schema_version = '{_SCHEMA}'", name=f"ck_{table}_schema")


def _identity_check(table: str) -> CheckConstraint:
    return CheckConstraint(f"length(record_identity) = {_IDENTITY}", name=f"ck_{table}_identity")


def _owner_check(table: str) -> CheckConstraint:
    return CheckConstraint("length(owner_id) > 0", name=f"ck_{table}_owner")


class AuthorityApprovalRequestRow(Base):
    """One persisted, non-authoritative approval request."""

    __tablename__ = "authority_approval_requests"
    __table_args__ = (
        PrimaryKeyConstraint("id", "owner_id", name="pk_authority_requests_owner"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_authority_requests_idempotency"),
        Index("ix_authority_requests_owner_created", "owner_id", "requested_at"),
        _owner_check("authority_requests"),
        _schema_check("authority_requests"),
        _identity_check("authority_requests"),
    )

    id: Mapped[str] = mapped_column(String(_ID))
    owner_id: Mapped[str] = mapped_column(String(_OWNER))
    schema_version: Mapped[str] = mapped_column(String(48))
    requested_by: Mapped[str] = mapped_column(String(_ID))
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(_ID))
    capability: Mapped[str] = mapped_column(String(_CAP))
    policy_version: Mapped[str] = mapped_column(String(_POLICY))
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(_IDEMPOTENCY))
    record_identity: Mapped[str] = mapped_column(String(_IDENTITY))
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuthorityApprovalDecisionRow(Base):
    """One append-only approval decision (approved or rejected)."""

    __tablename__ = "authority_approval_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("id", "owner_id", name="pk_authority_decisions_owner"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_authority_decisions_idempotency"),
        ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["authority_approval_requests.id", "authority_approval_requests.owner_id"],
            name="fk_authority_decisions_request_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_authority_decisions_owner_request", "owner_id", "request_id"),
        _owner_check("authority_decisions"),
        _schema_check("authority_decisions"),
        _identity_check("authority_decisions"),
        CheckConstraint(
            "outcome IN ('approved', 'rejected')", name="ck_authority_decisions_outcome"
        ),
    )

    id: Mapped[str] = mapped_column(String(_ID))
    owner_id: Mapped[str] = mapped_column(String(_OWNER))
    schema_version: Mapped[str] = mapped_column(String(48))
    request_id: Mapped[str] = mapped_column(String(_ID))
    decided_by: Mapped[str] = mapped_column(String(_ID))
    outcome: Mapped[str] = mapped_column(String(16))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime)
    capability: Mapped[str] = mapped_column(String(_CAP))
    policy_version: Mapped[str] = mapped_column(String(_POLICY))
    idempotency_key: Mapped[str] = mapped_column(String(_IDEMPOTENCY))
    record_identity: Mapped[str] = mapped_column(String(_IDENTITY))
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuthorityCapabilityGrantRow(Base):
    """One immutable capability grant, issued only from an approved decision."""

    __tablename__ = "authority_capability_grants"
    __table_args__ = (
        PrimaryKeyConstraint("id", "owner_id", name="pk_authority_grants_owner"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_authority_grants_idempotency"),
        ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["authority_approval_requests.id", "authority_approval_requests.owner_id"],
            name="fk_authority_grants_request_owner",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["decision_id", "owner_id"],
            ["authority_approval_decisions.id", "authority_approval_decisions.owner_id"],
            name="fk_authority_grants_decision_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_authority_grants_owner_decision", "owner_id", "decision_id"),
        _owner_check("authority_grants"),
        _schema_check("authority_grants"),
        _identity_check("authority_grants"),
        CheckConstraint("valid_from < expires_at", name="ck_authority_grants_window"),
        CheckConstraint("delegation = 'prohibited'", name="ck_authority_grants_delegation"),
    )

    id: Mapped[str] = mapped_column(String(_ID))
    owner_id: Mapped[str] = mapped_column(String(_OWNER))
    schema_version: Mapped[str] = mapped_column(String(48))
    request_id: Mapped[str] = mapped_column(String(_ID))
    decision_id: Mapped[str] = mapped_column(String(_ID))
    issued_by: Mapped[str] = mapped_column(String(_ID))
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime)
    subject_type: Mapped[str] = mapped_column(String(32))
    subject_id: Mapped[str] = mapped_column(String(_ID))
    capability: Mapped[str] = mapped_column(String(_CAP))
    policy_version: Mapped[str] = mapped_column(String(_POLICY))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    delegation: Mapped[str] = mapped_column(String(16))
    idempotency_key: Mapped[str] = mapped_column(String(_IDEMPOTENCY))
    record_identity: Mapped[str] = mapped_column(String(_IDENTITY))
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuthorityRevocationRow(Base):
    """One append-only revocation evidence record for a grant."""

    __tablename__ = "authority_revocations"
    __table_args__ = (
        PrimaryKeyConstraint("id", "owner_id", name="pk_authority_revocations_owner"),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_authority_revocations_idempotency"
        ),
        ForeignKeyConstraint(
            ["grant_id", "owner_id"],
            ["authority_capability_grants.id", "authority_capability_grants.owner_id"],
            name="fk_authority_revocations_grant_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_authority_revocations_owner_grant", "owner_id", "grant_id"),
        _owner_check("authority_revocations"),
        _schema_check("authority_revocations"),
        _identity_check("authority_revocations"),
    )

    id: Mapped[str] = mapped_column(String(_ID))
    owner_id: Mapped[str] = mapped_column(String(_OWNER))
    schema_version: Mapped[str] = mapped_column(String(48))
    grant_id: Mapped[str] = mapped_column(String(_ID))
    revoked_by: Mapped[str] = mapped_column(String(_ID))
    effective_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(_IDEMPOTENCY))
    record_identity: Mapped[str] = mapped_column(String(_IDENTITY))
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSON)


class AuthorityEvaluationRow(Base):
    """One append-only authority-evaluation evidence record."""

    __tablename__ = "authority_evaluations"
    __table_args__ = (
        PrimaryKeyConstraint("id", "owner_id", name="pk_authority_evaluations_owner"),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_authority_evaluations_idempotency"
        ),
        ForeignKeyConstraint(
            ["grant_id", "owner_id"],
            ["authority_capability_grants.id", "authority_capability_grants.owner_id"],
            name="fk_authority_evaluations_grant_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_authority_evaluations_owner_grant", "owner_id", "grant_id"),
        _owner_check("authority_evaluations"),
        _schema_check("authority_evaluations"),
        _identity_check("authority_evaluations"),
    )

    id: Mapped[str] = mapped_column(String(_ID))
    owner_id: Mapped[str] = mapped_column(String(_OWNER))
    schema_version: Mapped[str] = mapped_column(String(48))
    grant_id: Mapped[str] = mapped_column(String(_ID))
    request_id: Mapped[str] = mapped_column(String(_ID))
    decision_id: Mapped[str] = mapped_column(String(_ID))
    evaluation_time: Mapped[datetime] = mapped_column(UTCDateTime)
    capability: Mapped[str] = mapped_column(String(_CAP))
    policy_version: Mapped[str] = mapped_column(String(_POLICY))
    allowed: Mapped[bool] = mapped_column(Boolean)
    reason_code: Mapped[str] = mapped_column(String(48))
    relevant_revocation_id: Mapped[str | None] = mapped_column(String(_ID), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(_IDEMPOTENCY))
    record_identity: Mapped[str] = mapped_column(String(_IDENTITY))
    request_payload: Mapped[dict[str, object]] = mapped_column(JSON)
    decision_payload: Mapped[dict[str, object]] = mapped_column(JSON)
