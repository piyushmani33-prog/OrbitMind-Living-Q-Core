"""phase 4a corrective relational integrity

Adds the foreign keys + unique checksum constraint that the original Phase 4A migration
(6df90052521e) omitted (review findings #9/#11). Additive + reversible; named constraints
so downgrade works on PostgreSQL. SQLite uses batch (table-recreate) mode.

Revision ID: d63d75f51b9d
Revises: 6df90052521e
Create Date: 2026-06-21 09:48:38.088323
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa  # noqa: F401
from alembic import op

revision: str = "d63d75f51b9d"
down_revision: str | None = "6df90052521e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FKS = (
    (
        "benchmark_comparisons",
        "fk_benchmark_comparisons_benchmark_id",
        "benchmark_runs",
        "benchmark_id",
    ),
    ("benchmark_runs", "fk_benchmark_runs_problem_id", "optimization_problems", "problem_id"),
    ("optimization_artifacts", "fk_optimization_artifacts_scope_id", "benchmark_runs", "scope_id"),
    (
        "quantum_experiments",
        "fk_quantum_experiments_benchmark_id",
        "benchmark_runs",
        "benchmark_id",
    ),
    ("solver_runs", "fk_solver_runs_benchmark_id", "benchmark_runs", "benchmark_id"),
)


def upgrade() -> None:
    for table, name, ref, col in _FKS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.create_foreign_key(name, ref, [col], ["id"])
    with op.batch_alter_table("optimization_problems", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_optimization_problems_checksum"))
        batch_op.create_index(
            batch_op.f("ix_optimization_problems_checksum"), ["checksum"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("optimization_problems", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_optimization_problems_checksum"))
        batch_op.create_index(
            batch_op.f("ix_optimization_problems_checksum"), ["checksum"], unique=False
        )
    for table, name, _ref, _col in _FKS:
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_constraint(name, type_="foreignkey")
