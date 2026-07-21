"""operation admission v0 evidence

Revision ID: a1f4c7e9b230
Revises: 9313833e1f07
Create Date: 2026-07-21 12:20:00.000000

Adds the single append-only, owner-scoped Operation Admission v0 evidence table
``operation_admission_records`` (U7.4). This migration creates ONLY the admission
table; it deliberately excludes unrelated autogenerate drift for other domains.

The ``resolved_authority_grant_id`` column carries a **nullable, owner-qualified**
foreign key to ``authority_capability_grants`` (populated only when a real
owner-scoped grant was resolved); the FK-free ``requested_authority_grant_id`` may
hold an id that never resolved. ``ondelete="RESTRICT"`` prevents authority
evidence from being erased by cascade.

Downgrade drops the admission table and therefore permanently discards the
admission evidence it holds. Downgrade is intended for development/test rollback of
an unreleased schema only; take a backup first
(see docs/operations/DATABASE_MIGRATION_BACKUP.md) in any environment that has
recorded real admission decisions.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import orbitmind.persistence.database

revision: str = "a1f4c7e9b230"
down_revision: str | None = "9313833e1f07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operation_admission_records",
        sa.Column("admission_id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("proposal_id", sa.String(length=128), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("operation_kind", sa.String(length=64), nullable=False),
        sa.Column("requested_capability", sa.String(length=64), nullable=False),
        sa.Column("side_effect_class", sa.String(length=32), nullable=False),
        sa.Column("risk_class", sa.String(length=16), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("primary_reason_code", sa.String(length=48), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("requested_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("requested_authority_grant_id", sa.String(length=128), nullable=True),
        sa.Column("resolved_authority_grant_id", sa.String(length=128), nullable=True),
        sa.Column("proposal_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision_checksum", sa.String(length=64), nullable=False),
        sa.Column("record_identity", sa.String(length=64), nullable=False),
        sa.Column("created_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_admission_records_owner"),
        sa.CheckConstraint(
            "schema_version = 'operation-admission-v0'", name="ck_admission_records_schema"
        ),
        sa.CheckConstraint("length(record_identity) = 64", name="ck_admission_records_identity"),
        sa.CheckConstraint(
            "outcome IN ('admitted', 'denied', 'approval_required')",
            name="ck_admission_records_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_authority_grant_id", "owner_id"],
            ["authority_capability_grants.id", "authority_capability_grants.owner_id"],
            name="fk_admission_records_resolved_grant_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("admission_id", "owner_id", name="pk_admission_records_owner"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_admission_records_idempotency"),
    )
    op.create_index(
        "ix_admission_records_owner_created",
        "operation_admission_records",
        ["owner_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_admission_records_owner_created", table_name="operation_admission_records")
    op.drop_table("operation_admission_records")
