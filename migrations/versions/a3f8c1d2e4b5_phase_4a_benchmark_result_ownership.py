"""phase 4a benchmark result ownership

Adds explicit ownership anchors + database-enforced ownership constraints (third Codex review,
High #2): a problem_id on solver_runs / quantum_experiments / benchmark_comparisons, composite
UNIQUE(benchmark_id, id) on the result tables, and composite FKs binding each comparison
association id to a row OWNED BY THE SAME benchmark. Additive + reversible; explicit constraint
names; SQLite uses batch (table-recreate) mode.

Revision ID: a3f8c1d2e4b5
Revises: c7e1f2a9d3b4
Create Date: 2026-06-21 18:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f8c1d2e4b5"
down_revision: str | None = "c7e1f2a9d3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("solver_runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("problem_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_solver_runs_problem_id", ["problem_id"])
        batch_op.create_unique_constraint("uq_solver_runs_owner", ["benchmark_id", "id"])
    with op.batch_alter_table("quantum_experiments", schema=None) as batch_op:
        batch_op.add_column(sa.Column("problem_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_quantum_experiments_problem_id", ["problem_id"])
        batch_op.create_unique_constraint("uq_quantum_experiments_owner", ["benchmark_id", "id"])
    with op.batch_alter_table("benchmark_comparisons", schema=None) as batch_op:
        batch_op.add_column(sa.Column("problem_id", sa.String(length=36), nullable=True))
        batch_op.create_index("ix_benchmark_comparisons_problem_id", ["problem_id"])
        batch_op.create_foreign_key(
            "fk_comparison_exact_owner",
            "solver_runs",
            ["benchmark_id", "exact_result_id"],
            ["benchmark_id", "id"],
        )
        batch_op.create_foreign_key(
            "fk_comparison_greedy_owner",
            "solver_runs",
            ["benchmark_id", "greedy_result_id"],
            ["benchmark_id", "id"],
        )
        batch_op.create_foreign_key(
            "fk_comparison_quantum_owner",
            "quantum_experiments",
            ["benchmark_id", "quantum_experiment_id"],
            ["benchmark_id", "id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("benchmark_comparisons", schema=None) as batch_op:
        batch_op.drop_constraint("fk_comparison_quantum_owner", type_="foreignkey")
        batch_op.drop_constraint("fk_comparison_greedy_owner", type_="foreignkey")
        batch_op.drop_constraint("fk_comparison_exact_owner", type_="foreignkey")
        batch_op.drop_index("ix_benchmark_comparisons_problem_id")
        batch_op.drop_column("problem_id")
    with op.batch_alter_table("quantum_experiments", schema=None) as batch_op:
        batch_op.drop_constraint("uq_quantum_experiments_owner", type_="unique")
        batch_op.drop_index("ix_quantum_experiments_problem_id")
        batch_op.drop_column("problem_id")
    with op.batch_alter_table("solver_runs", schema=None) as batch_op:
        batch_op.drop_constraint("uq_solver_runs_owner", type_="unique")
        batch_op.drop_index("ix_solver_runs_problem_id")
        batch_op.drop_column("problem_id")
