"""SQLAlchemy ORM models for Phase 4C observation-geometry persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class ObservationGeometryRequestRow(Base):
    """Immutable owner-scoped observation-geometry request snapshot."""

    __tablename__ = "observation_geometry_requests"
    __table_args__ = (
        Index("ix_og_requests_owner", "owner_id"),
        Index("ix_og_requests_checksum", "request_checksum"),
        Index("ix_og_requests_element", "element_checksum"),
        Index("ix_og_requests_source", "source_identity_checksum"),
        Index("ix_og_requests_site", "site_id"),
        Index("ix_og_requests_start", "start_at"),
        Index("ix_og_requests_created", "created_at"),
        UniqueConstraint("id", "owner_id", name="uq_og_requests_owner"),
        UniqueConstraint("owner_id", "request_checksum", name="uq_og_requests_owner_checksum"),
        UniqueConstraint("owner_id", "idempotency_key", name="uq_og_requests_idempotency"),
        CheckConstraint("length(owner_id) > 0", name="ck_og_requests_owner_nonempty"),
        CheckConstraint("length(request_checksum) = 64", name="ck_og_requests_checksum_len"),
        CheckConstraint("length(element_checksum) = 64", name="ck_og_requests_element_len"),
        CheckConstraint("length(source_identity_checksum) = 64", name="ck_og_requests_source_len"),
        CheckConstraint("request_schema_version = '1'", name="ck_og_requests_schema"),
        CheckConstraint("end_at > start_at", name="ck_og_requests_end_after_start"),
        CheckConstraint("step_seconds >= 1 AND step_seconds <= 3600", name="ck_og_requests_step"),
        CheckConstraint(
            "minimum_elevation_deg >= 0 AND minimum_elevation_deg < 90",
            name="ck_og_requests_min_elevation",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    request_checksum: Mapped[str] = mapped_column(String(64))
    request_schema_version: Mapped[str] = mapped_column(String(16))
    element_checksum: Mapped[str] = mapped_column(String(64))
    source_identity_checksum: Mapped[str] = mapped_column(String(64))
    site_id: Mapped[str] = mapped_column(String(120))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    step_seconds: Mapped[int] = mapped_column(Integer)
    minimum_elevation_deg: Mapped[float] = mapped_column(Float)
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ObservationGeometryRunRow(Base):
    """Completed deterministic geometry run with authenticated result snapshot."""

    __tablename__ = "observation_geometry_runs"
    __table_args__ = (
        Index("ix_og_runs_owner", "owner_id"),
        Index("ix_og_runs_request", "request_id"),
        Index("ix_og_runs_request_checksum", "request_checksum"),
        Index("ix_og_runs_geometry", "geometry_checksum"),
        Index("ix_og_runs_element", "element_checksum"),
        Index("ix_og_runs_source", "source_identity_checksum"),
        Index("ix_og_runs_status", "run_status"),
        Index("ix_og_runs_created", "created_at"),
        UniqueConstraint("id", "owner_id", name="uq_og_runs_owner"),
        UniqueConstraint("owner_id", "request_id", name="uq_og_runs_owner_request"),
        ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["observation_geometry_requests.id", "observation_geometry_requests.owner_id"],
            name="fk_og_runs_request_owner",
        ),
        CheckConstraint("length(owner_id) > 0", name="ck_og_runs_owner_nonempty"),
        CheckConstraint("length(request_checksum) = 64", name="ck_og_runs_request_len"),
        CheckConstraint("length(geometry_checksum) = 64", name="ck_og_runs_geometry_len"),
        CheckConstraint("length(element_checksum) = 64", name="ck_og_runs_element_len"),
        CheckConstraint("length(source_identity_checksum) = 64", name="ck_og_runs_source_len"),
        CheckConstraint("result_schema_version = '1'", name="ck_og_runs_schema"),
        CheckConstraint(
            "computation_version = 'orbitmind-look-angle-geometry-1.0'",
            name="ck_og_runs_computation_version",
        ),
        CheckConstraint("run_status = 'completed'", name="ck_og_runs_status"),
        CheckConstraint(
            "epistemic_status = 'deterministic-calculation'",
            name="ck_og_runs_epistemic",
        ),
        CheckConstraint("sample_count >= 0 AND sample_count <= 100000", name="ck_og_runs_samples"),
        CheckConstraint(
            "failed_sample_count >= 0 AND failed_sample_count <= sample_count",
            name="ck_og_runs_failed_samples",
        ),
        CheckConstraint(
            "interval_count >= 0 AND interval_count <= 1024",
            name="ck_og_runs_intervals",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    request_id: Mapped[str] = mapped_column(String(36))
    request_checksum: Mapped[str] = mapped_column(String(64))
    geometry_checksum: Mapped[str] = mapped_column(String(64))
    element_checksum: Mapped[str] = mapped_column(String(64))
    source_identity_checksum: Mapped[str] = mapped_column(String(64))
    result_schema_version: Mapped[str] = mapped_column(String(16))
    computation_version: Mapped[str] = mapped_column(String(64))
    run_status: Mapped[str] = mapped_column(String(16))
    epistemic_status: Mapped[str] = mapped_column(String(48))
    sample_count: Mapped[int] = mapped_column(Integer)
    failed_sample_count: Mapped[int] = mapped_column(Integer)
    interval_count: Mapped[int] = mapped_column(Integer)
    limitations_json: Mapped[list[str]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime)
