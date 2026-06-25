"""phase 4b provenance anchored planning links

Adds immutable owner-scoped derivation links from authenticated provenance and eligibility
sets to persisted observation-planning requests, runs, and optional plans. These links are
not signed receipts and do not introduce APIs, artifacts, approval, memory, providers,
geometry, quantum execution, or command authority.

Revision ID: k6e7f8a9b0c2
Revises: j6e7f8a9b0c1
Create Date: 2026-06-25 16:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import orbitmind.persistence.database

revision: str = "k6e7f8a9b0c2"
down_revision: str | None = "j6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINK_INDEXES = {
    "owner_id": "ix_oppl_owner",
    "provenance_record_id": "ix_oppl_provenance",
    "eligibility_set_record_id": "ix_oppl_eligibility_set",
    "preparation_checksum": "ix_oppl_preparation",
    "planning_request_id": "ix_oppl_request",
    "planning_run_id": "ix_oppl_run",
    "observation_plan_id": "ix_oppl_plan",
    "link_checksum": "ix_oppl_checksum",
    "created_at": "ix_oppl_created_at",
}


def upgrade() -> None:
    with op.batch_alter_table("observation_plans") as batch_op:
        batch_op.create_unique_constraint("uq_observation_plans_owner", ["id", "owner_id"])

    op.create_table(
        "observation_planning_provenance_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("provenance_record_id", sa.String(length=36), nullable=False),
        sa.Column("provenance_checksum", sa.String(length=64), nullable=False),
        sa.Column("eligibility_set_record_id", sa.String(length=36), nullable=False),
        sa.Column("eligibility_set_checksum", sa.String(length=64), nullable=False),
        sa.Column("preparation_checksum", sa.String(length=64), nullable=False),
        sa.Column("planning_request_checksum", sa.String(length=64), nullable=False),
        sa.Column("planning_scientific_identity_checksum", sa.String(length=64), nullable=False),
        sa.Column("planning_request_id", sa.String(length=36), nullable=False),
        sa.Column("planning_run_id", sa.String(length=36), nullable=False),
        sa.Column("observation_plan_id", sa.String(length=36), nullable=True),
        sa.Column("selected_window_ids_json", sa.JSON(), nullable=False),
        sa.Column("planning_status", sa.String(length=32), nullable=False),
        sa.Column("authoritative_solver", sa.String(length=16), nullable=True),
        sa.Column("optimality_label", sa.String(length=16), nullable=False),
        sa.Column("feasible", sa.Boolean(), nullable=False),
        sa.Column("objective_value", sa.Float(), nullable=True),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("link_schema_version", sa.String(length=48), nullable=False),
        sa.Column("link_json", sa.JSON(), nullable=False),
        sa.Column("link_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_planning_provenance_links"),
        sa.UniqueConstraint("id", "owner_id", name="uq_oppl_owner"),
        sa.UniqueConstraint("owner_id", "link_checksum", name="uq_oppl_owner_checksum"),
        sa.UniqueConstraint(
            "owner_id",
            "preparation_checksum",
            "planning_run_id",
            name="uq_oppl_owner_preparation_run",
        ),
        sa.ForeignKeyConstraint(
            ["provenance_record_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oppl_provenance_owner",
        ),
        sa.ForeignKeyConstraint(
            ["eligibility_set_record_id", "owner_id"],
            [
                "observation_eligibility_window_sets.id",
                "observation_eligibility_window_sets.owner_id",
            ],
            name="fk_oppl_eligibility_set_owner",
        ),
        sa.ForeignKeyConstraint(
            ["planning_request_id", "owner_id"],
            ["observation_planning_requests.id", "observation_planning_requests.owner_id"],
            name="fk_oppl_request_owner",
        ),
        sa.ForeignKeyConstraint(
            ["planning_run_id", "owner_id"],
            ["observation_planning_runs.id", "observation_planning_runs.owner_id"],
            name="fk_oppl_run_owner",
        ),
        sa.ForeignKeyConstraint(
            ["observation_plan_id", "owner_id"],
            ["observation_plans.id", "observation_plans.owner_id"],
            name="fk_oppl_plan_owner",
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_oppl_owner_nonempty"),
        sa.CheckConstraint("length(provenance_checksum) = 64", name="ck_oppl_provenance_len"),
        sa.CheckConstraint("length(eligibility_set_checksum) = 64", name="ck_oppl_set_len"),
        sa.CheckConstraint("length(preparation_checksum) = 64", name="ck_oppl_preparation_len"),
        sa.CheckConstraint("length(planning_request_checksum) = 64", name="ck_oppl_request_len"),
        sa.CheckConstraint(
            "length(planning_scientific_identity_checksum) = 64",
            name="ck_oppl_identity_len",
        ),
        sa.CheckConstraint("length(link_checksum) = 64", name="ck_oppl_checksum_len"),
        sa.CheckConstraint(
            "link_schema_version = 'observation-planning-provenance-link-v1'",
            name="ck_oppl_schema_version",
        ),
        sa.CheckConstraint(
            "planning_status IN ('verified-feasible', 'infeasible', 'timed-out', "
            "'unsupported', 'invalid', 'failed')",
            name="ck_oppl_status",
        ),
        sa.CheckConstraint(
            "optimality_label IN ('optimal', 'heuristic', 'infeasible', 'unknown')",
            name="ck_oppl_optimality",
        ),
        sa.CheckConstraint(
            "authoritative_solver IS NULL OR authoritative_solver IN ('exact', 'greedy')",
            name="ck_oppl_solver",
        ),
        sa.CheckConstraint(
            "(planning_status = 'verified-feasible' AND feasible = true "
            "AND observation_plan_id IS NOT NULL) OR "
            "(planning_status <> 'verified-feasible' AND feasible = false "
            "AND observation_plan_id IS NULL)",
            name="ck_oppl_status_plan",
        ),
    )
    for column, index_name in _LINK_INDEXES.items():
        op.create_index(index_name, "observation_planning_provenance_links", [column])


def downgrade() -> None:
    for index_name in reversed(_LINK_INDEXES.values()):
        op.drop_index(index_name, table_name="observation_planning_provenance_links")
    op.drop_table("observation_planning_provenance_links")
    with op.batch_alter_table("observation_plans") as batch_op:
        batch_op.drop_constraint("uq_observation_plans_owner", type_="unique")
