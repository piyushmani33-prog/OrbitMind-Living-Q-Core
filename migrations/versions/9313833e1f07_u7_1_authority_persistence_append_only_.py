"""u7 1 authority persistence append only records

Revision ID: 9313833e1f07
Revises: n9c0d1e2f3g4
Create Date: 2026-07-18 23:02:49.855166

Adds the five append-only, owner-scoped U7 authority evidence tables. This
migration creates ONLY the authority tables; it deliberately excludes unrelated
autogenerate drift for other domains.

Downgrade drops the authority tables and therefore permanently discards the
authority evidence they hold. Downgrade is intended for development/test rollback
of an unreleased schema only; it is NOT a safe way to dispose of authority audit
evidence in an environment that has recorded real approvals, grants, revocations,
or evaluations. Take a backup first (see docs/operations/DATABASE_MIGRATION_BACKUP.md).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import orbitmind.persistence.database

revision: str = "9313833e1f07"
down_revision: str | None = "n9c0d1e2f3g4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authority_approval_requests",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("requested_by", sa.String(length=128), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("requested_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("valid_from", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("expires_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("record_identity", sa.String(length=64), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'authority-contracts-v1'", name="ck_authority_requests_schema"
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_authority_requests_owner"),
        sa.CheckConstraint("length(record_identity) = 64", name="ck_authority_requests_identity"),
        sa.PrimaryKeyConstraint("id", "owner_id", name="pk_authority_requests_owner"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_authority_requests_idempotency"
        ),
    )
    op.create_index(
        "ix_authority_requests_owner_created",
        "authority_approval_requests",
        ["owner_id", "requested_at"],
        unique=False,
    )

    op.create_table(
        "authority_approval_decisions",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("decided_by", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("decided_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("record_identity", sa.String(length=64), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('approved', 'rejected')", name="ck_authority_decisions_outcome"
        ),
        sa.CheckConstraint(
            "schema_version = 'authority-contracts-v1'", name="ck_authority_decisions_schema"
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_authority_decisions_owner"),
        sa.CheckConstraint("length(record_identity) = 64", name="ck_authority_decisions_identity"),
        sa.ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["authority_approval_requests.id", "authority_approval_requests.owner_id"],
            name="fk_authority_decisions_request_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", "owner_id", name="pk_authority_decisions_owner"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_authority_decisions_idempotency"
        ),
    )
    op.create_index(
        "ix_authority_decisions_owner_request",
        "authority_approval_decisions",
        ["owner_id", "request_id"],
        unique=False,
    )

    op.create_table(
        "authority_capability_grants",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("decision_id", sa.String(length=128), nullable=False),
        sa.Column("issued_by", sa.String(length=128), nullable=False),
        sa.Column("issued_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("valid_from", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("expires_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("delegation", sa.String(length=16), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("record_identity", sa.String(length=64), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint("delegation = 'prohibited'", name="ck_authority_grants_delegation"),
        sa.CheckConstraint(
            "schema_version = 'authority-contracts-v1'", name="ck_authority_grants_schema"
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_authority_grants_owner"),
        sa.CheckConstraint("length(record_identity) = 64", name="ck_authority_grants_identity"),
        sa.CheckConstraint("valid_from < expires_at", name="ck_authority_grants_window"),
        sa.ForeignKeyConstraint(
            ["decision_id", "owner_id"],
            ["authority_approval_decisions.id", "authority_approval_decisions.owner_id"],
            name="fk_authority_grants_decision_owner",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id", "owner_id"],
            ["authority_approval_requests.id", "authority_approval_requests.owner_id"],
            name="fk_authority_grants_request_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", "owner_id", name="pk_authority_grants_owner"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_authority_grants_idempotency"),
    )
    op.create_index(
        "ix_authority_grants_owner_decision",
        "authority_capability_grants",
        ["owner_id", "decision_id"],
        unique=False,
    )

    op.create_table(
        "authority_revocations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("grant_id", sa.String(length=128), nullable=False),
        sa.Column("revoked_by", sa.String(length=128), nullable=False),
        sa.Column("effective_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("recorded_at", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("record_identity", sa.String(length=64), nullable=False),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'authority-contracts-v1'", name="ck_authority_revocations_schema"
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_authority_revocations_owner"),
        sa.CheckConstraint(
            "length(record_identity) = 64", name="ck_authority_revocations_identity"
        ),
        sa.ForeignKeyConstraint(
            ["grant_id", "owner_id"],
            ["authority_capability_grants.id", "authority_capability_grants.owner_id"],
            name="fk_authority_revocations_grant_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", "owner_id", name="pk_authority_revocations_owner"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_authority_revocations_idempotency"
        ),
    )
    op.create_index(
        "ix_authority_revocations_owner_grant",
        "authority_revocations",
        ["owner_id", "grant_id"],
        unique=False,
    )

    op.create_table(
        "authority_evaluations",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("schema_version", sa.String(length=48), nullable=False),
        sa.Column("grant_id", sa.String(length=128), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("decision_id", sa.String(length=128), nullable=False),
        sa.Column("evaluation_time", orbitmind.persistence.database.UTCDateTime(), nullable=False),
        sa.Column("capability", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason_code", sa.String(length=48), nullable=False),
        sa.Column("relevant_revocation_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("record_identity", sa.String(length=64), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("decision_payload", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 'authority-contracts-v1'", name="ck_authority_evaluations_schema"
        ),
        sa.CheckConstraint("length(owner_id) > 0", name="ck_authority_evaluations_owner"),
        sa.CheckConstraint(
            "length(record_identity) = 64", name="ck_authority_evaluations_identity"
        ),
        sa.ForeignKeyConstraint(
            ["grant_id", "owner_id"],
            ["authority_capability_grants.id", "authority_capability_grants.owner_id"],
            name="fk_authority_evaluations_grant_owner",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", "owner_id", name="pk_authority_evaluations_owner"),
        sa.UniqueConstraint(
            "owner_id", "idempotency_key", name="uq_authority_evaluations_idempotency"
        ),
    )
    op.create_index(
        "ix_authority_evaluations_owner_grant",
        "authority_evaluations",
        ["owner_id", "grant_id"],
        unique=False,
    )


def downgrade() -> None:
    # Child tables first (RESTRICT foreign keys). This permanently discards
    # authority evidence — back up first in any environment with real records.
    op.drop_index("ix_authority_evaluations_owner_grant", table_name="authority_evaluations")
    op.drop_table("authority_evaluations")
    op.drop_index("ix_authority_revocations_owner_grant", table_name="authority_revocations")
    op.drop_table("authority_revocations")
    op.drop_index("ix_authority_grants_owner_decision", table_name="authority_capability_grants")
    op.drop_table("authority_capability_grants")
    op.drop_index("ix_authority_decisions_owner_request", table_name="authority_approval_decisions")
    op.drop_table("authority_approval_decisions")
    op.drop_index("ix_authority_requests_owner_created", table_name="authority_approval_requests")
    op.drop_table("authority_approval_requests")
