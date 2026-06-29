"""phase 4c observation geometry persistence

Adds immutable owner-scoped request and completed-run persistence for bounded
observation geometry. Samples and visibility intervals remain inside the authenticated
canonical result JSON for this slice.

Revision ID: l7a8b9c0d1e2
Revises: k6e7f8a9b0c2
Create Date: 2026-06-29 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import orbitmind.persistence.database

revision: str = "l7a8b9c0d1e2"
down_revision: str | None = "k6e7f8a9b0c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REQUEST_INDEXES = {
    "owner_id": "ix_og_requests_owner",
    "request_checksum": "ix_og_requests_checksum",
    "element_checksum": "ix_og_requests_element",
    "source_identity_checksum": "ix_og_requests_source",
    "site_id": "ix_og_requests_site",
    "start_at": "ix_og_requests_start",
    "created_at": "ix_og_requests_created",
}

_RUN_INDEXES = {
    "owner_id": "ix_og_runs_owner",
    "request_id": "ix_og_runs_request",
    "request_checksum": "ix_og_runs_request_checksum",
    "geometry_checksum": "ix_og_runs_geometry",
    "element_checksum": "ix_og_runs_element",
    "source_identity_checksum": "ix_og_runs_source",
    "run_status": "ix_og_runs_status",
    "created_at": "ix_og_runs_created",
}


def upgrade() -> None:
    op.create_table(
        "observation_geometry_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("request_checksum", sa.String(length=64), nullable=False),
        sa.Column("request_schema_version", sa.String(length=16), nullable=False),
        sa.Column("element_checksum", sa.String(length=64), nullable=False),
        sa.Column("source_identity_checksum", sa.String(length=64), nullable=False),
        sa.Column("site_id", sa.String(length=120), nullable=False),
        sa.Column("start_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("end_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("step_seconds", sa.Integer(), nullable=False),
        sa.Column("minimum_elevation_deg", sa.Float(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_geometry_requests"),
        sa.UniqueConstraint("id", "owner_id", name="uq_og_requests_owner"),
        sa.UniqueConstraint("owner_id", "request_checksum", name="uq_og_requests_owner_checksum"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_og_requests_idempotency"),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_og_requests_owner_nonempty"),
        sa.CheckConstraint("length(request_checksum) = 64", name="ck_og_requests_checksum_len"),
        sa.CheckConstraint("length(element_checksum) = 64", name="ck_og_requests_element_len"),
        sa.CheckConstraint(
            "length(source_identity_checksum) = 64", name="ck_og_requests_source_len"
        ),
        sa.CheckConstraint("request_schema_version = '1'", name="ck_og_requests_schema"),
        sa.CheckConstraint("end_at > start_at", name="ck_og_requests_end_after_start"),
        sa.CheckConstraint(
            "step_seconds >= 1 AND step_seconds <= 3600", name="ck_og_requests_step"
        ),
        sa.CheckConstraint(
            "minimum_elevation_deg >= 0 AND minimum_elevation_deg < 90",
            name="ck_og_requests_min_elevation",
        ),
    )
    for column, index_name in _REQUEST_INDEXES.items():
        op.create_index(index_name, "observation_geometry_requests", [column])

    op.create_table(
        "observation_geometry_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=False),
        sa.Column("request_checksum", sa.String(length=64), nullable=False),
        sa.Column("geometry_checksum", sa.String(length=64), nullable=False),
        sa.Column("element_checksum", sa.String(length=64), nullable=False),
        sa.Column("source_identity_checksum", sa.String(length=64), nullable=False),
        sa.Column("result_schema_version", sa.String(length=16), nullable=False),
        sa.Column("computation_version", sa.String(length=64), nullable=False),
        sa.Column("run_status", sa.String(length=16), nullable=False),
        sa.Column("epistemic_status", sa.String(length=48), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("failed_sample_count", sa.Integer(), nullable=False),
        sa.Column("interval_count", sa.Integer(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("completed_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_geometry_runs"),
        sa.UniqueConstraint("id", "owner_id", name="uq_og_runs_owner"),
        sa.UniqueConstraint("owner_id", "request_id", name="uq_og_runs_owner_request"),
        sa.ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["observation_geometry_requests.id", "observation_geometry_requests.owner_id"],
            name="fk_og_runs_request_owner",
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_og_runs_owner_nonempty"),
        sa.CheckConstraint("length(request_checksum) = 64", name="ck_og_runs_request_len"),
        sa.CheckConstraint("length(geometry_checksum) = 64", name="ck_og_runs_geometry_len"),
        sa.CheckConstraint("length(element_checksum) = 64", name="ck_og_runs_element_len"),
        sa.CheckConstraint("length(source_identity_checksum) = 64", name="ck_og_runs_source_len"),
        sa.CheckConstraint("result_schema_version = '1'", name="ck_og_runs_schema"),
        sa.CheckConstraint(
            "computation_version = 'orbitmind-look-angle-geometry-1.0'",
            name="ck_og_runs_computation_version",
        ),
        sa.CheckConstraint("run_status = 'completed'", name="ck_og_runs_status"),
        sa.CheckConstraint(
            "epistemic_status = 'deterministic-calculation'",
            name="ck_og_runs_epistemic",
        ),
        sa.CheckConstraint(
            "sample_count >= 0 AND sample_count <= 100000", name="ck_og_runs_samples"
        ),
        sa.CheckConstraint(
            "failed_sample_count >= 0 AND failed_sample_count <= sample_count",
            name="ck_og_runs_failed_samples",
        ),
        sa.CheckConstraint(
            "interval_count >= 0 AND interval_count <= 1024",
            name="ck_og_runs_intervals",
        ),
    )
    for column, index_name in _RUN_INDEXES.items():
        op.create_index(index_name, "observation_geometry_runs", [column])


def downgrade() -> None:
    for index_name in reversed(_RUN_INDEXES.values()):
        op.drop_index(index_name, table_name="observation_geometry_runs")
    op.drop_table("observation_geometry_runs")
    for index_name in reversed(_REQUEST_INDEXES.values()):
        op.drop_index(index_name, table_name="observation_geometry_requests")
    op.drop_table("observation_geometry_requests")
