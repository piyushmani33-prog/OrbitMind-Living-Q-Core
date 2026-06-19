"""SQLAlchemy ORM models (the persistence schema).

These are deliberately separate from the Pydantic domain models. Binary images are
never stored here — only artifact metadata + filesystem paths (DATA_MODEL.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class MissionRow(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    satellite_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized_request: Mapped[dict[str, Any]] = mapped_column(JSON)
    epistemic_status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class MissionInputRow(Base):
    __tablename__ = "mission_inputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    workflow_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class OrbitalSampleRow(Base):
    __tablename__ = "orbital_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    pos_x_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    pos_y_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    pos_z_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    vel_x_kmps: Mapped[float | None] = mapped_column(Float, nullable=True)
    vel_y_kmps: Mapped[float | None] = mapped_column(Float, nullable=True)
    vel_z_kmps: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    alt_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(8))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_orbital_samples_mission_ts", "mission_id", "ts"),)


class VerificationFindingRow(Base):
    __tablename__ = "verification_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    explanation: Mapped[str] = mapped_column(Text)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProvenanceRow(Base):
    __tablename__ = "provenance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    subject_ref: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str] = mapped_column(String(128))
    method: Mapped[str] = mapped_column(String(64))
    inputs_hash: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ArtifactRow(Base):
    __tablename__ = "artifact_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(255))
    sidecar_path: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
