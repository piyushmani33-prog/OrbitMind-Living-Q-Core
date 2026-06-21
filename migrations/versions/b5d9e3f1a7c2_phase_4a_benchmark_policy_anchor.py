"""phase 4a benchmark policy anchor

Persists the immutable server-owned policy snapshot on the benchmark PARENT (third Codex
review, High #3): policy id/version/checksum + canonical snapshot JSON on benchmark_runs, so a
comparison-only policy swap is rejected and an old benchmark stays verifiable after a policy is
retired. Additive + reversible; SQLite uses batch (table-recreate) mode.

Revision ID: b5d9e3f1a7c2
Revises: a3f8c1d2e4b5
Create Date: 2026-06-21 19:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5d9e3f1a7c2"
down_revision: str | None = "a3f8c1d2e4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("policy_id", sa.String(length=64)),
    ("policy_version", sa.String(length=16)),
    ("policy_checksum", sa.String(length=64)),
    ("policy_snapshot_json", sa.JSON()),
)


def upgrade() -> None:
    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        for name, col_type in _COLUMNS:
            batch_op.add_column(sa.Column(name, col_type, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("benchmark_runs", schema=None) as batch_op:
        for name, _type in reversed(_COLUMNS):
            batch_op.drop_column(name)
