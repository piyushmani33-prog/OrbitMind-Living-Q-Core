"""phase 4a execution receipts

Adds the signed benchmark execution-receipt table (third Codex review, High #1). Stores only
PUBLIC receipt metadata (payload + checksum + signature + signer key id) — never the signing
secret. One receipt per benchmark. Additive + reversible; explicit constraint names.

Revision ID: c9a1b3e5d7f2
Revises: b5d9e3f1a7c2
Create Date: 2026-06-21 19:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a1b3e5d7f2"
down_revision: str | None = "b5d9e3f1a7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "benchmark_execution_receipts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("benchmark_id", sa.String(length=36), nullable=False),
        sa.Column("signer_key_id", sa.String(length=64), nullable=False),
        sa.Column("signature_algorithm", sa.String(length=32), nullable=False),
        sa.Column("payload_checksum", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_benchmark_execution_receipts"),
        sa.ForeignKeyConstraint(
            ["benchmark_id"],
            ["benchmark_runs.id"],
            name="fk_execution_receipt_benchmark_id",
        ),
        sa.UniqueConstraint("benchmark_id", name="uq_execution_receipt_benchmark"),
    )
    op.create_index(
        "ix_benchmark_execution_receipts_signer_key_id",
        "benchmark_execution_receipts",
        ["signer_key_id"],
    )
    op.create_index(
        "ix_benchmark_execution_receipts_created_at",
        "benchmark_execution_receipts",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_benchmark_execution_receipts_created_at", table_name="benchmark_execution_receipts"
    )
    op.drop_index(
        "ix_benchmark_execution_receipts_signer_key_id", table_name="benchmark_execution_receipts"
    )
    op.drop_table("benchmark_execution_receipts")
