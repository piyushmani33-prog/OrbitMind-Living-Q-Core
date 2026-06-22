"""phase 4a receipt replay guard

Hardens benchmark execution receipts against replay (fourth Codex review, Medium #1). Adds a
dedicated ``worker_execution_nonce`` column and database-level uniqueness on the signed
payload checksum and on the worker nonce, so the same signed payload or the same worker
execution nonce cannot be bound to two receipts. The nonce column is nullable (classical-only
receipts carry no worker nonce); NULLs remain distinct under the unique index on both
PostgreSQL and SQLite. Additive + reversible; explicit constraint names; batch ops for SQLite.

Revision ID: e1f2a3b4c5d6
Revises: c9a1b3e5d7f2
Create Date: 2026-06-22 12:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "c9a1b3e5d7f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "benchmark_execution_receipts"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("worker_execution_nonce", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_execution_receipt_payload_checksum", ["payload_checksum"])
        batch.create_unique_constraint("uq_execution_receipt_worker_nonce", ["worker_execution_nonce"])


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint("uq_execution_receipt_worker_nonce", type_="unique")
        batch.drop_constraint("uq_execution_receipt_payload_checksum", type_="unique")
        batch.drop_column("worker_execution_nonce")
