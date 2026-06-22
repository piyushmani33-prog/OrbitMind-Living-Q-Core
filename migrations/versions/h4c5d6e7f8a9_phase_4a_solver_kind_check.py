"""phase 4a solver kind check

Restricts persisted ``solver_runs.solver_kind`` to the two classical roles (final acceptance,
Medium). PostgreSQL then rejects an unreferenced bogus role (``bogus``, ``quantum-qaoa``, the
empty string, or a mis-cased ``Exact``); quantum experiments remain in their own table. Additive;
explicit constraint name; reversible. PostgreSQL-only (SQLite builds the identical CHECK via
create_all from the ORM models).

Revision ID: h4c5d6e7f8a9
Revises: g3b4c5d6e7f8
Create Date: 2026-06-23 09:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "h4c5d6e7f8a9"
down_revision: str | None = "g3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite builds this CHECK from the ORM models via create_all
    op.create_check_constraint(
        "ck_solver_runs_kind", "solver_runs", "solver_kind IN ('exact', 'greedy')"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.drop_constraint("ck_solver_runs_kind", "solver_runs", type_="check")
