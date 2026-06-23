"""phase 4a memory edge benchmark scope

Scopes optimization-generated scientific-memory edges to the exact benchmark that created them
(fifth review, High #3). Adds a nullable ``benchmark_id`` ownership column + index to
``memory_graph_edges`` so a benchmark's evidence graph selects ONLY its own edges and a tamper of
one benchmark cannot affect another's edges. Additive + reversible; explicit names; batch ops
for SQLite. Non-optimization edges leave ``benchmark_id`` NULL.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-22 18:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "memory_graph_edges"
_INDEX = "ix_memory_graph_edges_benchmark_id"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("benchmark_id", sa.String(length=36), nullable=True))
    op.create_index(_INDEX, _TABLE, ["benchmark_id"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column("benchmark_id")
