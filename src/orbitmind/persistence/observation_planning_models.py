"""SQLAlchemy ORM models for Phase 4B observation-planning persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class ObservationPlanningRequestRow(Base):
    __tablename__ = "observation_planning_requests"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_observation_planning_requests_owner"),
        UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_observation_planning_request_idempotency"
        ),
        CheckConstraint("length(request_checksum) = 64", name="ck_op_requests_checksum_len"),
        CheckConstraint(
            "source_mode IN ('fixture', 'declared')", name="ck_op_requests_source_mode"
        ),
        CheckConstraint(
            "request_schema_version = 'observation-planning-request-v1'",
            name="ck_op_requests_schema_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120), index=True)
    request_checksum: Mapped[str] = mapped_column(String(64), index=True)
    source_mode: Mapped[str] = mapped_column(String(16), index=True)
    request_schema_version: Mapped[str] = mapped_column(String(48))
    request_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ObservationPlanningRunRow(Base):
    __tablename__ = "observation_planning_runs"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_observation_planning_runs_owner"),
        UniqueConstraint(
            "request_id",
            "scientific_identity_checksum",
            name="uq_observation_planning_run_identity",
        ),
        ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["observation_planning_requests.id", "observation_planning_requests.owner_id"],
            name="fk_op_runs_request_owner",
        ),
        CheckConstraint("length(request_checksum) = 64", name="ck_op_runs_request_checksum_len"),
        CheckConstraint("length(problem_checksum) = 64", name="ck_op_runs_problem_checksum_len"),
        CheckConstraint(
            "length(scientific_identity_checksum) = 64",
            name="ck_op_runs_identity_len",
        ),
        CheckConstraint("source_mode IN ('fixture', 'declared')", name="ck_op_runs_source_mode"),
        CheckConstraint(
            "planning_status IN ('verified-feasible', 'infeasible', 'timed-out', "
            "'unsupported', 'invalid', 'failed')",
            name="ck_op_runs_status",
        ),
        CheckConstraint(
            "optimality_label IN ('optimal', 'heuristic', 'infeasible', 'unknown')",
            name="ck_op_runs_optimality",
        ),
        CheckConstraint(
            "authoritative_solver IS NULL OR authoritative_solver IN ('exact', 'greedy')",
            name="ck_op_runs_authoritative_solver",
        ),
        CheckConstraint(
            "verification_label IS NULL OR verification_label IN "
            "('verified-fixture-plan', 'verified-declared-opportunity-plan')",
            name="ck_op_runs_verification_label",
        ),
        CheckConstraint(
            "(planning_status = 'verified-feasible' AND feasible = true) OR "
            "(planning_status <> 'verified-feasible' AND feasible = false)",
            name="ck_op_runs_status_feasible",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(
        ForeignKey("observation_planning_requests.id"), index=True
    )
    owner_id: Mapped[str] = mapped_column(String(120), index=True)
    request_checksum: Mapped[str] = mapped_column(String(64), index=True)
    problem_checksum: Mapped[str] = mapped_column(String(64), index=True)
    planning_status: Mapped[str] = mapped_column(String(32), index=True)
    authoritative_solver: Mapped[str | None] = mapped_column(String(16), nullable=True)
    solver_execution_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    optimality_label: Mapped[str] = mapped_column(String(16), index=True)
    verification_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_mode: Mapped[str] = mapped_column(String(16), index=True)
    feasible: Mapped[bool] = mapped_column(Boolean)
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    result_schema_version: Mapped[str] = mapped_column(String(48))
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    scientific_identity_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    scientific_identity_checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ObservationPlanRow(Base):
    __tablename__ = "observation_plans"
    __table_args__ = (
        UniqueConstraint("run_id", name="uq_observation_plans_run"),
        ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["observation_planning_runs.id", "observation_planning_runs.owner_id"],
            name="fk_observation_plans_run_owner",
        ),
        CheckConstraint("length(problem_checksum) = 64", name="ck_observation_plans_problem_len"),
        CheckConstraint(
            "length(scientific_identity_checksum) = 64",
            name="ck_observation_plans_identity_len",
        ),
        CheckConstraint(
            "plan_schema_version = 'observation-plan-v1'",
            name="ck_observation_plans_schema_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("observation_planning_runs.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(120), index=True)
    problem_checksum: Mapped[str] = mapped_column(String(64), index=True)
    selected_opportunity_ids_json: Mapped[list[str]] = mapped_column(JSON)
    evaluation_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    limitations_json: Mapped[list[str]] = mapped_column(JSON)
    plan_schema_version: Mapped[str] = mapped_column(String(32))
    scientific_identity_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    scientific_identity_checksum: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
