"""phase 4a comparison associations + policy metadata

Adds association ids (exact/greedy/quantum run ids), the objective gap, and server-owned
comparison-policy metadata (id/version/checksum) to ``benchmark_comparisons`` so a comparison
round-trips its evidence associations and the policy can be authenticated (second Codex
review, findings #9/#17). Additive + reversible; SQLite uses batch (table-recreate) mode.

Revision ID: c7e1f2a9d3b4
Revises: d63d75f51b9d
Create Date: 2026-06-21 16:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e1f2a9d3b4"
down_revision: str | None = "d63d75f51b9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (name, column) for nullable association/gap columns.
_NULLABLE = (
    ("objective_gap", sa.Float()),
    ("exact_result_id", sa.String(length=36)),
    ("greedy_result_id", sa.String(length=36)),
    ("quantum_experiment_id", sa.String(length=36)),
)
# (name, column, server_default) for the not-null policy columns (back-fill existing rows).
_POLICY = (
    ("policy_id", sa.String(length=64), "strict-v1"),
    ("policy_version", sa.String(length=16), "1"),
    ("policy_checksum", sa.String(length=64), ""),
)


def upgrade() -> None:
    with op.batch_alter_table("benchmark_comparisons", schema=None) as batch_op:
        for name, col_type in _NULLABLE:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))
        for name, col_type, default in _POLICY:
            batch_op.add_column(sa.Column(name, col_type, nullable=False, server_default=default))


def downgrade() -> None:
    with op.batch_alter_table("benchmark_comparisons", schema=None) as batch_op:
        for name, _type, _default in _POLICY:
            batch_op.drop_column(name)
        for name, _type in _NULLABLE:
            batch_op.drop_column(name)
