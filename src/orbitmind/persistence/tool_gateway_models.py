"""Append-only ORM storage for non-executing gateway decision evidence."""

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


class OperationToolGatewayDecisionRow(Base):
    __tablename__ = "tool_gateway_decision_records"
    __table_args__ = (
        PrimaryKeyConstraint(
            "gateway_decision_id", "owner_id", name="pk_tool_gateway_records_owner"
        ),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_tool_gateway_records_idempotency"),
        ForeignKeyConstraint(
            ["resolved_admission_id", "owner_id"],
            ["operation_admission_records.admission_id", "operation_admission_records.owner_id"],
            name="fk_tool_gateway_records_resolved_admission_owner",
            ondelete="RESTRICT",
        ),
        Index("ix_tool_gateway_records_owner_created", "owner_id", "created_at"),
        CheckConstraint("length(owner_id) > 0", name="ck_tool_gateway_records_owner"),
        CheckConstraint(
            "schema_version = 'tool-gateway-v0'", name="ck_tool_gateway_records_schema"
        ),
        CheckConstraint("length(record_identity) = 64", name="ck_tool_gateway_records_identity"),
        CheckConstraint(
            "outcome IN ('eligible', 'denied', 'approval_required')",
            name="ck_tool_gateway_records_outcome",
        ),
    )
    gateway_decision_id: Mapped[str] = mapped_column(String(128))
    owner_id: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(48))
    proposal_id: Mapped[str] = mapped_column(String(128))
    actor_id: Mapped[str] = mapped_column(String(128))
    tool_id: Mapped[str] = mapped_column(String(64))
    tool_version: Mapped[str] = mapped_column(String(32))
    descriptor_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    referenced_admission_id: Mapped[str] = mapped_column(String(128))
    resolved_admission_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    admission_record_identity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32))
    primary_reason_code: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[str] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    proposal_fingerprint: Mapped[str] = mapped_column(String(64))
    decision_checksum: Mapped[str] = mapped_column(String(64))
    record_identity: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    idempotency_key: Mapped[str] = mapped_column(String(200))
    canonical_payload: Mapped[dict[str, object]] = mapped_column(JSON)
