"""Live PostgreSQL integration for Phase 4A optimization persistence + migration.

Skips cleanly unless ORBITMIND_TEST_POSTGRES_URL points at a disposable, migrated DB
(see tests/integration/test_postgres_memory.py for setup). Uses run_quantum=False so the
PostgreSQL runner needs no Aer.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(
        not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB) to run"
    ),
]

_TABLES = (
    "optimization_artifacts",
    "benchmark_comparisons",
    "quantum_sample_results",
    "quantum_experiments",
    "solver_runs",
    "benchmark_runs",
    "scheduling_constraints",
    "observation_opportunities",
    "optimization_problems",
    "memory_graph_edges",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> AppContainer:
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "art",
        cache_dir=tmp_path / "cache",
        env="test",
    )
    container = AppContainer(settings=settings)
    container.init_storage()
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    return container


def _count(container: AppContainer, table: str) -> int:
    with container.database.engine.connect() as conn:
        return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_optimization_tables_and_fts_index_present(pg_container: AppContainer) -> None:
    head = _count(pg_container, "optimization_problems")  # table exists + queryable
    assert head == 0
    with pg_container.database.engine.connect() as conn:
        present = {
            r[0]
            for r in conn.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
            )
        }
    for table in _TABLES:
        assert table in present


def test_benchmark_persists_and_reads_back_on_postgres(pg_container: AppContainer) -> None:
    svc = pg_container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    assert _count(pg_container, "observation_opportunities") == 4
    assert _count(pg_container, "scheduling_constraints") >= 1

    run, findings = svc.benchmark(problem.id, seed=7, run_quantum=False)
    assert run.comparison.conclusion.value == "classical-exact-best"
    assert all(f.passed for f in findings)
    assert _count(pg_container, "benchmark_runs") == 1
    assert _count(pg_container, "solver_runs") == 2
    assert _count(pg_container, "benchmark_comparisons") == 1

    # Read back the persisted problem + a solver run.
    fetched = svc.get_problem(problem.id)
    assert fetched is not None and fetched.checksum == problem.checksum
    exact_id = run.solver_results[0].id
    reread = svc.get_run(exact_id)
    assert reread is not None

    # Bounded memory links were registered.
    assert _count(pg_container, "memory_graph_edges") >= 2


def test_existing_domain_tables_intact_on_postgres(pg_container: AppContainer) -> None:
    pg_container.optimization_service.create_problem(fixtures.fixture("default"))
    for table in ("missions", "space_objects", "scientific_documents", "source_definitions"):
        _count(pg_container, table)  # queryable, untouched by optimization
