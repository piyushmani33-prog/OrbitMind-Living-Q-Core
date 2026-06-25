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
    Index,
    Integer,
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
        UniqueConstraint("id", "owner_id", name="uq_observation_plans_owner"),
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


class ObservationPlanningProvenanceLinkRow(Base):
    __tablename__ = "observation_planning_provenance_links"
    __table_args__ = (
        Index("ix_oppl_owner", "owner_id"),
        Index("ix_oppl_provenance", "provenance_record_id"),
        Index("ix_oppl_eligibility_set", "eligibility_set_record_id"),
        Index("ix_oppl_preparation", "preparation_checksum"),
        Index("ix_oppl_request", "planning_request_id"),
        Index("ix_oppl_run", "planning_run_id"),
        Index("ix_oppl_plan", "observation_plan_id"),
        Index("ix_oppl_checksum", "link_checksum"),
        Index("ix_oppl_created_at", "created_at"),
        UniqueConstraint("id", "owner_id", name="uq_oppl_owner"),
        UniqueConstraint("owner_id", "link_checksum", name="uq_oppl_owner_checksum"),
        UniqueConstraint(
            "owner_id",
            "preparation_checksum",
            "planning_run_id",
            name="uq_oppl_owner_preparation_run",
        ),
        ForeignKeyConstraint(
            ["provenance_record_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oppl_provenance_owner",
        ),
        ForeignKeyConstraint(
            ["eligibility_set_record_id", "owner_id"],
            [
                "observation_eligibility_window_sets.id",
                "observation_eligibility_window_sets.owner_id",
            ],
            name="fk_oppl_eligibility_set_owner",
        ),
        ForeignKeyConstraint(
            ["planning_request_id", "owner_id"],
            ["observation_planning_requests.id", "observation_planning_requests.owner_id"],
            name="fk_oppl_request_owner",
        ),
        ForeignKeyConstraint(
            ["planning_run_id", "owner_id"],
            ["observation_planning_runs.id", "observation_planning_runs.owner_id"],
            name="fk_oppl_run_owner",
        ),
        ForeignKeyConstraint(
            ["observation_plan_id", "owner_id"],
            ["observation_plans.id", "observation_plans.owner_id"],
            name="fk_oppl_plan_owner",
        ),
        CheckConstraint("length(owner_id) > 0", name="ck_oppl_owner_nonempty"),
        CheckConstraint("length(provenance_checksum) = 64", name="ck_oppl_provenance_len"),
        CheckConstraint("length(eligibility_set_checksum) = 64", name="ck_oppl_set_len"),
        CheckConstraint("length(preparation_checksum) = 64", name="ck_oppl_preparation_len"),
        CheckConstraint("length(planning_request_checksum) = 64", name="ck_oppl_request_len"),
        CheckConstraint(
            "length(planning_scientific_identity_checksum) = 64",
            name="ck_oppl_identity_len",
        ),
        CheckConstraint("length(link_checksum) = 64", name="ck_oppl_checksum_len"),
        CheckConstraint(
            "link_schema_version = 'observation-planning-provenance-link-v1'",
            name="ck_oppl_schema_version",
        ),
        CheckConstraint(
            "planning_status IN ('verified-feasible', 'infeasible', 'timed-out', "
            "'unsupported', 'invalid', 'failed')",
            name="ck_oppl_status",
        ),
        CheckConstraint(
            "optimality_label IN ('optimal', 'heuristic', 'infeasible', 'unknown')",
            name="ck_oppl_optimality",
        ),
        CheckConstraint(
            "authoritative_solver IS NULL OR authoritative_solver IN ('exact', 'greedy')",
            name="ck_oppl_solver",
        ),
        CheckConstraint(
            "(planning_status = 'verified-feasible' AND feasible = true "
            "AND observation_plan_id IS NOT NULL) OR "
            "(planning_status <> 'verified-feasible' AND feasible = false "
            "AND observation_plan_id IS NULL)",
            name="ck_oppl_status_plan",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    provenance_record_id: Mapped[str] = mapped_column(String(36))
    provenance_checksum: Mapped[str] = mapped_column(String(64))
    eligibility_set_record_id: Mapped[str] = mapped_column(String(36))
    eligibility_set_checksum: Mapped[str] = mapped_column(String(64))
    preparation_checksum: Mapped[str] = mapped_column(String(64))
    planning_request_checksum: Mapped[str] = mapped_column(String(64))
    planning_scientific_identity_checksum: Mapped[str] = mapped_column(String(64))
    planning_request_id: Mapped[str] = mapped_column(String(36))
    planning_run_id: Mapped[str] = mapped_column(String(36))
    observation_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    selected_window_ids_json: Mapped[list[str]] = mapped_column(JSON)
    planning_status: Mapped[str] = mapped_column(String(32))
    authoritative_solver: Mapped[str | None] = mapped_column(String(16), nullable=True)
    optimality_label: Mapped[str] = mapped_column(String(16))
    feasible: Mapped[bool] = mapped_column(Boolean)
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    limitations_json: Mapped[list[str]] = mapped_column(JSON)
    link_schema_version: Mapped[str] = mapped_column(String(48))
    link_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    link_checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ObservationInputProvenanceRow(Base):
    __tablename__ = "observation_input_provenance"
    __table_args__ = (
        Index("ix_oip_owner", "owner_id"),
        Index("ix_oip_checksum", "provenance_checksum"),
        Index("ix_oip_source_type", "source_type"),
        Index("ix_oip_verification", "verification_status"),
        Index("ix_oip_artifact_checksum", "artifact_checksum"),
        Index("ix_oip_created_at", "created_at"),
        UniqueConstraint("id", "owner_id", name="uq_observation_input_provenance_owner"),
        UniqueConstraint(
            "owner_id",
            "provenance_checksum",
            name="uq_observation_input_provenance_owner_checksum",
        ),
        CheckConstraint("length(owner_id) > 0", name="ck_oip_owner_nonempty"),
        CheckConstraint("length(provenance_checksum) = 64", name="ck_oip_checksum_len"),
        CheckConstraint("length(artifact_checksum) = 64", name="ck_oip_artifact_checksum_len"),
        CheckConstraint("schema_version = '1'", name="ck_oip_schema_version"),
        CheckConstraint(
            "source_type IN ('fixture', 'user_declared', 'derived')",
            name="ck_oip_source_type",
        ),
        CheckConstraint(
            "verification_status IN ('fixture_verified', 'user_declared', "
            "'derived_from_declared', 'unverified', 'unknown')",
            name="ck_oip_verification_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    provenance_checksum: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(16))
    source_type: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(32))
    provenance_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    artifact_checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ObservationInputProvenanceParentRow(Base):
    __tablename__ = "observation_input_provenance_parents"
    __table_args__ = (
        Index("ix_oipp_owner", "owner_id"),
        Index("ix_oipp_child", "child_provenance_id"),
        Index("ix_oipp_parent", "parent_provenance_id"),
        Index("ix_oipp_parent_checksum", "parent_provenance_checksum"),
        Index("ix_oipp_created_at", "created_at"),
        ForeignKeyConstraint(
            ["child_provenance_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oip_parents_child_owner",
        ),
        ForeignKeyConstraint(
            ["parent_provenance_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oip_parents_parent_owner",
        ),
        UniqueConstraint(
            "child_provenance_id",
            "parent_provenance_id",
            name="uq_oip_parents_child_parent",
        ),
        CheckConstraint(
            "child_provenance_id <> parent_provenance_id", name="ck_oip_no_self_parent"
        ),
        CheckConstraint(
            "length(parent_provenance_checksum) = 64",
            name="ck_oip_parent_checksum_len",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    child_provenance_id: Mapped[str] = mapped_column(String(36))
    parent_provenance_id: Mapped[str] = mapped_column(String(36))
    parent_provenance_checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ObservationEligibilityWindowSetRow(Base):
    __tablename__ = "observation_eligibility_window_sets"
    __table_args__ = (
        Index("ix_oews_owner", "owner_id"),
        Index("ix_oews_checksum", "eligibility_set_checksum"),
        Index("ix_oews_source", "source_provenance_id"),
        Index("ix_oews_source_checksum", "source_provenance_checksum"),
        Index("ix_oews_created_at", "created_at"),
        UniqueConstraint("id", "owner_id", name="uq_observation_eligibility_sets_owner"),
        UniqueConstraint(
            "owner_id",
            "eligibility_set_checksum",
            name="uq_observation_eligibility_sets_owner_checksum",
        ),
        ForeignKeyConstraint(
            ["source_provenance_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oews_source_provenance_owner",
        ),
        CheckConstraint("length(owner_id) > 0", name="ck_oews_owner_nonempty"),
        CheckConstraint(
            "length(eligibility_set_checksum) = 64",
            name="ck_oews_checksum_len",
        ),
        CheckConstraint(
            "length(source_provenance_checksum) = 64",
            name="ck_oews_provenance_checksum_len",
        ),
        CheckConstraint("schema_version = '1'", name="ck_oews_schema_version"),
        CheckConstraint("window_count >= 0 AND window_count <= 24", name="ck_oews_window_count"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    eligibility_set_checksum: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(16))
    source_provenance_id: Mapped[str] = mapped_column(String(36))
    source_provenance_checksum: Mapped[str] = mapped_column(String(64))
    generation_rule_version: Mapped[str] = mapped_column(String(120))
    window_count: Mapped[int] = mapped_column(Integer)
    limitations_json: Mapped[list[str]] = mapped_column(JSON)
    eligibility_set_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ObservationEligibilityWindowRow(Base):
    __tablename__ = "observation_eligibility_windows"
    __table_args__ = (
        Index("ix_oew_set", "set_id"),
        Index("ix_oew_owner", "owner_id"),
        Index("ix_oew_window", "window_id"),
        Index("ix_oew_asset", "asset_id"),
        Index("ix_oew_target", "target_id"),
        Index("ix_oew_start", "start_at"),
        Index("ix_oew_end", "end_at"),
        Index("ix_oew_source_checksum", "source_provenance_checksum"),
        Index("ix_oew_declaration", "declaration_mode"),
        Index("ix_oew_verification", "verification_status"),
        Index("ix_oew_created_at", "created_at"),
        ForeignKeyConstraint(
            ["set_id", "owner_id"],
            [
                "observation_eligibility_window_sets.id",
                "observation_eligibility_window_sets.owner_id",
            ],
            name="fk_oew_set_owner",
        ),
        UniqueConstraint("set_id", "window_id", name="uq_oew_set_window_id"),
        UniqueConstraint(
            "set_id",
            "asset_id",
            "target_id",
            "start_at",
            "end_at",
            name="uq_oew_set_scientific_window",
        ),
        CheckConstraint("end_at > start_at", name="ck_oew_end_after_start"),
        CheckConstraint(
            "length(source_provenance_checksum) = 64",
            name="ck_oew_provenance_checksum_len",
        ),
        CheckConstraint(
            "declaration_mode IN ('fixture_backed', 'user_declared', "
            "'derived_from_declared_input')",
            name="ck_oew_declaration_mode",
        ),
        CheckConstraint(
            "verification_status IN ('fixture_verified', 'user_declared', "
            "'derived_from_declared', 'unverified', 'unknown')",
            name="ck_oew_verification_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    set_id: Mapped[str] = mapped_column(String(36))
    owner_id: Mapped[str] = mapped_column(String(120))
    window_id: Mapped[str] = mapped_column(String(120))
    asset_id: Mapped[str] = mapped_column(String(120))
    target_id: Mapped[str] = mapped_column(String(120))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    source_provenance_checksum: Mapped[str] = mapped_column(String(64))
    declaration_mode: Mapped[str] = mapped_column(String(48))
    verification_status: Mapped[str] = mapped_column(String(32))
    window_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
