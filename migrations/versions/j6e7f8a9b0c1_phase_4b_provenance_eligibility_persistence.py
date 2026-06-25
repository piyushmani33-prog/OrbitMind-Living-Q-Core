"""phase 4b provenance and eligibility persistence

Adds immutable owner-scoped persistence for pinned scientific-input provenance and
declared/fixture-backed eligibility-window sets. This deliberately does not add APIs,
receipts, artifacts, live providers, geometry, approval, memory, quantum, or orchestration
wiring.

Revision ID: j6e7f8a9b0c1
Revises: i5d6e7f8a9b0
Create Date: 2026-06-25 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import orbitmind.persistence.database

revision: str = "j6e7f8a9b0c1"
down_revision: str | None = "i5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OIP_INDEXES = {
    "owner_id": "ix_oip_owner",
    "provenance_checksum": "ix_oip_checksum",
    "source_type": "ix_oip_source_type",
    "verification_status": "ix_oip_verification",
    "artifact_checksum": "ix_oip_artifact_checksum",
    "created_at": "ix_oip_created_at",
}
_OIP_PARENT_INDEXES = {
    "owner_id": "ix_oipp_owner",
    "child_provenance_id": "ix_oipp_child",
    "parent_provenance_id": "ix_oipp_parent",
    "parent_provenance_checksum": "ix_oipp_parent_checksum",
    "created_at": "ix_oipp_created_at",
}
_OEWS_INDEXES = {
    "owner_id": "ix_oews_owner",
    "eligibility_set_checksum": "ix_oews_checksum",
    "source_provenance_id": "ix_oews_source",
    "source_provenance_checksum": "ix_oews_source_checksum",
    "created_at": "ix_oews_created_at",
}
_OEW_INDEXES = {
    "set_id": "ix_oew_set",
    "owner_id": "ix_oew_owner",
    "window_id": "ix_oew_window",
    "asset_id": "ix_oew_asset",
    "target_id": "ix_oew_target",
    "start_at": "ix_oew_start",
    "end_at": "ix_oew_end",
    "source_provenance_checksum": "ix_oew_source_checksum",
    "declaration_mode": "ix_oew_declaration",
    "verification_status": "ix_oew_verification",
    "created_at": "ix_oew_created_at",
}


def upgrade() -> None:
    op.create_table(
        "observation_input_provenance",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("provenance_checksum", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("artifact_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_input_provenance"),
        sa.UniqueConstraint("id", "owner_id", name="uq_observation_input_provenance_owner"),
        sa.UniqueConstraint(
            "owner_id",
            "provenance_checksum",
            name="uq_observation_input_provenance_owner_checksum",
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_oip_owner_nonempty"),
        sa.CheckConstraint("length(provenance_checksum) = 64", name="ck_oip_checksum_len"),
        sa.CheckConstraint("length(artifact_checksum) = 64", name="ck_oip_artifact_checksum_len"),
        sa.CheckConstraint("schema_version = '1'", name="ck_oip_schema_version"),
        sa.CheckConstraint(
            "source_type IN ('fixture', 'user_declared', 'derived')",
            name="ck_oip_source_type",
        ),
        sa.CheckConstraint(
            "verification_status IN ('fixture_verified', 'user_declared', "
            "'derived_from_declared', 'unverified', 'unknown')",
            name="ck_oip_verification_status",
        ),
    )
    for column, index_name in _OIP_INDEXES.items():
        op.create_index(index_name, "observation_input_provenance", [column])

    op.create_table(
        "observation_input_provenance_parents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("child_provenance_id", sa.String(length=36), nullable=False),
        sa.Column("parent_provenance_id", sa.String(length=36), nullable=False),
        sa.Column("parent_provenance_checksum", sa.String(length=64), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_input_provenance_parents"),
        sa.ForeignKeyConstraint(
            ["child_provenance_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oip_parents_child_owner",
        ),
        sa.ForeignKeyConstraint(
            ["parent_provenance_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oip_parents_parent_owner",
        ),
        sa.UniqueConstraint(
            "child_provenance_id",
            "parent_provenance_id",
            name="uq_oip_parents_child_parent",
        ),
        sa.CheckConstraint(
            "child_provenance_id <> parent_provenance_id",
            name="ck_oip_no_self_parent",
        ),
        sa.CheckConstraint(
            "length(parent_provenance_checksum) = 64",
            name="ck_oip_parent_checksum_len",
        ),
    )
    for column, index_name in _OIP_PARENT_INDEXES.items():
        op.create_index(
            index_name,
            "observation_input_provenance_parents",
            [column],
        )

    op.create_table(
        "observation_eligibility_window_sets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("eligibility_set_checksum", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), nullable=False),
        sa.Column("source_provenance_id", sa.String(length=36), nullable=False),
        sa.Column("source_provenance_checksum", sa.String(length=64), nullable=False),
        sa.Column("generation_rule_version", sa.String(length=120), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("limitations_json", sa.JSON(), nullable=False),
        sa.Column("eligibility_set_json", sa.JSON(), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_eligibility_window_sets"),
        sa.UniqueConstraint("id", "owner_id", name="uq_observation_eligibility_sets_owner"),
        sa.UniqueConstraint(
            "owner_id",
            "eligibility_set_checksum",
            name="uq_observation_eligibility_sets_owner_checksum",
        ),
        sa.ForeignKeyConstraint(
            ["source_provenance_id", "owner_id"],
            ["observation_input_provenance.id", "observation_input_provenance.owner_id"],
            name="fk_oews_source_provenance_owner",
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_oews_owner_nonempty"),
        sa.CheckConstraint(
            "length(eligibility_set_checksum) = 64",
            name="ck_oews_checksum_len",
        ),
        sa.CheckConstraint(
            "length(source_provenance_checksum) = 64",
            name="ck_oews_provenance_checksum_len",
        ),
        sa.CheckConstraint("schema_version = '1'", name="ck_oews_schema_version"),
        sa.CheckConstraint("window_count >= 0 AND window_count <= 24", name="ck_oews_window_count"),
    )
    for column, index_name in _OEWS_INDEXES.items():
        op.create_index(
            index_name,
            "observation_eligibility_window_sets",
            [column],
        )

    op.create_table(
        "observation_eligibility_windows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("set_id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("window_id", sa.String(length=120), nullable=False),
        sa.Column("asset_id", sa.String(length=120), nullable=False),
        sa.Column("target_id", sa.String(length=120), nullable=False),
        sa.Column("start_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("end_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("source_provenance_checksum", sa.String(length=64), nullable=False),
        sa.Column("declaration_mode", sa.String(length=48), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("window_json", sa.JSON(), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_observation_eligibility_windows"),
        sa.ForeignKeyConstraint(
            ["set_id", "owner_id"],
            [
                "observation_eligibility_window_sets.id",
                "observation_eligibility_window_sets.owner_id",
            ],
            name="fk_oew_set_owner",
        ),
        sa.UniqueConstraint("set_id", "window_id", name="uq_oew_set_window_id"),
        sa.UniqueConstraint(
            "set_id",
            "asset_id",
            "target_id",
            "start_at",
            "end_at",
            name="uq_oew_set_scientific_window",
        ),
        sa.CheckConstraint("end_at > start_at", name="ck_oew_end_after_start"),
        sa.CheckConstraint(
            "length(source_provenance_checksum) = 64",
            name="ck_oew_provenance_checksum_len",
        ),
        sa.CheckConstraint(
            "declaration_mode IN ('fixture_backed', 'user_declared', "
            "'derived_from_declared_input')",
            name="ck_oew_declaration_mode",
        ),
        sa.CheckConstraint(
            "verification_status IN ('fixture_verified', 'user_declared', "
            "'derived_from_declared', 'unverified', 'unknown')",
            name="ck_oew_verification_status",
        ),
    )
    for column, index_name in _OEW_INDEXES.items():
        op.create_index(
            index_name,
            "observation_eligibility_windows",
            [column],
        )


def downgrade() -> None:
    for index_name in reversed(_OEW_INDEXES.values()):
        op.drop_index(
            index_name,
            table_name="observation_eligibility_windows",
        )
    op.drop_table("observation_eligibility_windows")

    for index_name in reversed(_OEWS_INDEXES.values()):
        op.drop_index(
            index_name,
            table_name="observation_eligibility_window_sets",
        )
    op.drop_table("observation_eligibility_window_sets")

    for index_name in reversed(_OIP_PARENT_INDEXES.values()):
        op.drop_index(
            index_name,
            table_name="observation_input_provenance_parents",
        )
    op.drop_table("observation_input_provenance_parents")

    for index_name in reversed(_OIP_INDEXES.values()):
        op.drop_index(
            index_name,
            table_name="observation_input_provenance",
        )
    op.drop_table("observation_input_provenance")
