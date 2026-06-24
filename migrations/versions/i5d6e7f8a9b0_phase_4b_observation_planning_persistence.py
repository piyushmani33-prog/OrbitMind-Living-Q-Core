"""phase 4b observation planning persistence

Adds the minimal immutable observation-planning envelope for Phase 4B.1:
request snapshots, planning runs, and verified-feasible plans. This deliberately
does not add APIs, receipts, sidecars, approval, memory edges, artifacts, quantum
persistence, or access-window geometry.

Revision ID: i5d6e7f8a9b0
Revises: h4c5d6e7f8a9
Create Date: 2026-06-24 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import orbitmind.persistence.database

revision: str = "i5d6e7f8a9b0"
down_revision: str | None = "h4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "observation_planning_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("request_checksum", sa.String(length=64), nullable=False),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("request_schema_version", sa.String(length=48), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_planning_requests"),
        sa.UniqueConstraint("id", "owner_id", name="uq_observation_planning_requests_owner"),
        sa.UniqueConstraint(
            "owner_id",
            "idempotency_key",
            name="uq_observation_planning_request_idempotency",
        ),
        sa.CheckConstraint("length(request_checksum) = 64", name="ck_op_requests_checksum_len"),
        sa.CheckConstraint(
            "source_mode IN ('fixture', 'declared')",
            name="ck_op_requests_source_mode",
        ),
        sa.CheckConstraint(
            "request_schema_version = 'observation-planning-request-v1'",
            name="ck_op_requests_schema_version",
        ),
    )
    op.create_index(
        "ix_observation_planning_requests_owner_id",
        "observation_planning_requests",
        ["owner_id"],
    )
    op.create_index(
        "ix_observation_planning_requests_request_checksum",
        "observation_planning_requests",
        ["request_checksum"],
    )
    op.create_index(
        "ix_observation_planning_requests_source_mode",
        "observation_planning_requests",
        ["source_mode"],
    )
    op.create_index(
        "ix_observation_planning_requests_created_at",
        "observation_planning_requests",
        ["created_at"],
    )

    op.create_table(
        "observation_planning_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("request_checksum", sa.String(length=64), nullable=False),
        sa.Column("problem_checksum", sa.String(length=64), nullable=False),
        sa.Column("planning_status", sa.String(length=32), nullable=False),
        sa.Column("authoritative_solver", sa.String(length=16), nullable=True),
        sa.Column("solver_execution_status", sa.String(length=16), nullable=True),
        sa.Column("optimality_label", sa.String(length=16), nullable=False),
        sa.Column("verification_label", sa.String(length=64), nullable=True),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("objective_value", sa.Float(), nullable=True),
        sa.Column("result_schema_version", sa.String(length=48), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("scientific_identity_json", sa.JSON(), nullable=False),
        sa.Column("scientific_identity_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("completed_at", orbitmind.persistence.database.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_observation_planning_runs"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["observation_planning_requests.id"],
            name="fk_observation_planning_runs_request_id",
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["observation_planning_requests.id", "observation_planning_requests.owner_id"],
            name="fk_op_runs_request_owner",
        ),
        sa.UniqueConstraint("id", "owner_id", name="uq_observation_planning_runs_owner"),
        sa.UniqueConstraint(
            "request_id",
            "scientific_identity_checksum",
            name="uq_observation_planning_run_identity",
        ),
        sa.CheckConstraint("length(request_checksum) = 64", name="ck_op_runs_request_checksum_len"),
        sa.CheckConstraint("length(problem_checksum) = 64", name="ck_op_runs_problem_checksum_len"),
        sa.CheckConstraint(
            "length(scientific_identity_checksum) = 64",
            name="ck_op_runs_identity_len",
        ),
        sa.CheckConstraint("source_mode IN ('fixture', 'declared')", name="ck_op_runs_source_mode"),
        sa.CheckConstraint(
            "planning_status IN ('verified-feasible', 'infeasible', 'timed-out', "
            "'unsupported', 'invalid', 'failed')",
            name="ck_op_runs_status",
        ),
        sa.CheckConstraint(
            "optimality_label IN ('optimal', 'heuristic', 'infeasible', 'unknown')",
            name="ck_op_runs_optimality",
        ),
        sa.CheckConstraint(
            "authoritative_solver IS NULL OR authoritative_solver IN ('exact', 'greedy')",
            name="ck_op_runs_authoritative_solver",
        ),
        sa.CheckConstraint(
            "verification_label IS NULL OR verification_label IN "
            "('verified-fixture-plan', 'verified-declared-opportunity-plan')",
            name="ck_op_runs_verification_label",
        ),
        sa.CheckConstraint(
            "(planning_status = 'verified-feasible' AND feasible = true) OR "
            "(planning_status <> 'verified-feasible' AND feasible = false)",
            name="ck_op_runs_status_feasible",
        ),
    )
    for column in (
        "request_id",
        "owner_id",
        "request_checksum",
        "problem_checksum",
        "planning_status",
        "optimality_label",
        "source_mode",
        "scientific_identity_checksum",
        "created_at",
    ):
        op.create_index(
            f"ix_observation_planning_runs_{column}",
            "observation_planning_runs",
            [column],
        )

    op.create_table(
        "observation_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("problem_checksum", sa.String(length=64), nullable=False),
        sa.Column("selected_opportunity_ids_json", sa.JSON(), nullable=False),
        sa.Column("evaluation_json", sa.JSON(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("plan_schema_version", sa.String(length=32), nullable=False),
        sa.Column("scientific_identity_json", sa.JSON(), nullable=False),
        sa.Column("scientific_identity_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_plans"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["observation_planning_runs.id"],
            name="fk_observation_plans_run_id",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "owner_id"],
            ["observation_planning_runs.id", "observation_planning_runs.owner_id"],
            name="fk_observation_plans_run_owner",
        ),
        sa.UniqueConstraint("run_id", name="uq_observation_plans_run"),
        sa.CheckConstraint(
            "length(problem_checksum) = 64", name="ck_observation_plans_problem_len"
        ),
        sa.CheckConstraint(
            "length(scientific_identity_checksum) = 64",
            name="ck_observation_plans_identity_len",
        ),
        sa.CheckConstraint(
            "plan_schema_version = 'observation-plan-v1'",
            name="ck_observation_plans_schema_version",
        ),
    )
    for column in (
        "run_id",
        "owner_id",
        "problem_checksum",
        "scientific_identity_checksum",
        "created_at",
    ):
        op.create_index(
            f"ix_observation_plans_{column}",
            "observation_plans",
            [column],
        )


def downgrade() -> None:
    for column in (
        "created_at",
        "scientific_identity_checksum",
        "problem_checksum",
        "owner_id",
        "run_id",
    ):
        op.drop_index(f"ix_observation_plans_{column}", table_name="observation_plans")
    op.drop_table("observation_plans")

    for column in (
        "created_at",
        "scientific_identity_checksum",
        "source_mode",
        "optimality_label",
        "planning_status",
        "problem_checksum",
        "request_checksum",
        "owner_id",
        "request_id",
    ):
        op.drop_index(
            f"ix_observation_planning_runs_{column}",
            table_name="observation_planning_runs",
        )
    op.drop_table("observation_planning_runs")

    op.drop_index(
        "ix_observation_planning_requests_created_at",
        table_name="observation_planning_requests",
    )
    op.drop_index(
        "ix_observation_planning_requests_source_mode",
        table_name="observation_planning_requests",
    )
    op.drop_index(
        "ix_observation_planning_requests_request_checksum",
        table_name="observation_planning_requests",
    )
    op.drop_index(
        "ix_observation_planning_requests_owner_id",
        table_name="observation_planning_requests",
    )
    op.drop_table("observation_planning_requests")
