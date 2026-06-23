"""phase 4a solver role + ownership constraints

Enforces solver ROLE and benchmark/problem OWNERSHIP at the PostgreSQL level (fifth review,
High #4). Adds fixed solver-role columns on benchmark_comparisons (pinned by CHECK), a role-aware
composite unique on solver_runs, a composite-unique (id, problem_id) on benchmark_runs, role-aware
composite FKs for the exact/greedy comparison slots, and (benchmark_id, problem_id) ownership FKs
from solver/quantum/comparison rows to the parent benchmark. Additive; explicit names; reversible.

PostgreSQL-only (the SQLite test path builds the identical schema via create_all from the ORM
models). Revision ID: g3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-06-22 18:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g3b4c5d6e7f8"
down_revision: str | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite builds this schema from the ORM models via create_all
    # Fixed, CHECK-pinned solver-role columns on the comparison.
    op.add_column(
        "benchmark_comparisons",
        sa.Column(
            "exact_solver_kind", sa.String(length=24), nullable=False, server_default="exact"
        ),
    )
    op.add_column(
        "benchmark_comparisons",
        sa.Column(
            "greedy_solver_kind", sa.String(length=24), nullable=False, server_default="greedy"
        ),
    )
    op.create_check_constraint(
        "ck_comparison_exact_role", "benchmark_comparisons", "exact_solver_kind = 'exact'"
    )
    op.create_check_constraint(
        "ck_comparison_greedy_role", "benchmark_comparisons", "greedy_solver_kind = 'greedy'"
    )
    # Composite-unique FK targets.
    op.create_unique_constraint(
        "uq_benchmark_runs_id_problem", "benchmark_runs", ["id", "problem_id"]
    )
    op.create_unique_constraint(
        "uq_solver_runs_role_owner",
        "solver_runs",
        ["benchmark_id", "id", "problem_id", "solver_kind"],
    )
    # Replace the role-agnostic exact/greedy owner FKs with ROLE-AWARE composite FKs.
    op.drop_constraint("fk_comparison_exact_owner", "benchmark_comparisons", type_="foreignkey")
    op.drop_constraint("fk_comparison_greedy_owner", "benchmark_comparisons", type_="foreignkey")
    op.create_foreign_key(
        "fk_comparison_exact_role_owner",
        "benchmark_comparisons",
        "solver_runs",
        ["benchmark_id", "exact_result_id", "problem_id", "exact_solver_kind"],
        ["benchmark_id", "id", "problem_id", "solver_kind"],
    )
    op.create_foreign_key(
        "fk_comparison_greedy_role_owner",
        "benchmark_comparisons",
        "solver_runs",
        ["benchmark_id", "greedy_result_id", "problem_id", "greedy_solver_kind"],
        ["benchmark_id", "id", "problem_id", "solver_kind"],
    )
    # (benchmark_id, problem_id) ownership anchors to the parent benchmark+problem.
    for table, name in (
        ("solver_runs", "fk_solver_runs_benchmark_problem"),
        ("quantum_experiments", "fk_quantum_benchmark_problem"),
        ("benchmark_comparisons", "fk_comparison_benchmark_problem"),
    ):
        op.create_foreign_key(
            name,
            table,
            "benchmark_runs",
            ["benchmark_id", "problem_id"],
            ["id", "problem_id"],
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, name in (
        ("solver_runs", "fk_solver_runs_benchmark_problem"),
        ("quantum_experiments", "fk_quantum_benchmark_problem"),
        ("benchmark_comparisons", "fk_comparison_benchmark_problem"),
    ):
        op.drop_constraint(name, table, type_="foreignkey")
    op.drop_constraint(
        "fk_comparison_greedy_role_owner", "benchmark_comparisons", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_comparison_exact_role_owner", "benchmark_comparisons", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_comparison_exact_owner",
        "benchmark_comparisons",
        "solver_runs",
        ["benchmark_id", "exact_result_id"],
        ["benchmark_id", "id"],
    )
    op.create_foreign_key(
        "fk_comparison_greedy_owner",
        "benchmark_comparisons",
        "solver_runs",
        ["benchmark_id", "greedy_result_id"],
        ["benchmark_id", "id"],
    )
    op.drop_constraint("uq_solver_runs_role_owner", "solver_runs", type_="unique")
    op.drop_constraint("uq_benchmark_runs_id_problem", "benchmark_runs", type_="unique")
    op.drop_constraint("ck_comparison_greedy_role", "benchmark_comparisons", type_="check")
    op.drop_constraint("ck_comparison_exact_role", "benchmark_comparisons", type_="check")
    op.drop_column("benchmark_comparisons", "greedy_solver_kind")
    op.drop_column("benchmark_comparisons", "exact_solver_kind")
