"""Failure-injection: artifact cleanup + durable failure audits (third review, Medium #3)."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository


def _count(container: AppContainer, sql: str) -> int:
    with container.database.engine.connect() as conn:
        return int(conn.execute(text(sql)).scalar_one())


def _benchmark_rows(container: AppContainer) -> int:
    return _count(container, "SELECT count(*) FROM benchmark_runs")


def _failure_audits(container: AppContainer) -> int:
    return _count(
        container,
        "SELECT count(*) FROM audit_events WHERE action='optimization.benchmark_failed'",
    )


def _artifact_dirs(container: AppContainer) -> list[str]:
    root = container.settings.resolved_artifacts_dir()
    if not root.exists():
        return []
    return [p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]


def _inject(container: AppContainer, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    svc = container.optimization_service
    if stage == "verification":
        monkeypatch.setattr(
            "orbitmind.optimization.service.verify_benchmark",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom-verify")),
        )
    elif stage == "artifact-generation":
        monkeypatch.setattr(
            svc._viz, "generate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom-gen"))
        )
    elif stage == "persistence":
        monkeypatch.setattr(
            SqlAlchemyOptimizationRepository,
            "save_benchmark",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom-persist")),
        )
    elif stage == "memory":
        monkeypatch.setattr(
            svc,
            "_register_memory_links",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom-memory")),
        )


@pytest.mark.parametrize("stage", ["verification", "artifact-generation", "persistence", "memory"])
def test_failure_leaves_no_accepted_benchmark_or_orphans_and_audits(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    _inject(container, monkeypatch, stage)
    with pytest.raises(RuntimeError):
        container.optimization_service.benchmark(
            problem.id, seed=7, run_quantum=False, generate_artifacts=True
        )
    # No accepted (or any) benchmark row, no orphan artifact directories, a durable failure audit.
    assert _benchmark_rows(container) == 0
    assert _artifact_dirs(container) == []
    assert _failure_audits(container) >= 1
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert neighbors.neighbors == []


def test_retry_after_failure_succeeds_without_duplicates(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    _inject(container, monkeypatch, "persistence")
    with pytest.raises(RuntimeError):
        container.optimization_service.benchmark(
            problem.id, seed=7, run_quantum=False, generate_artifacts=True
        )
    monkeypatch.undo()  # remove the injected failure, then retry
    run, findings = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    assert all(f.passed for f in findings)
    session = container.database.session()
    accepted = SqlAlchemyOptimizationRepository(session).get_benchmark(run.id)
    session.close()
    assert accepted is not None and accepted.verification_passed is True
    # Exactly one benchmark + one artifact directory; memory edges created once.
    assert _benchmark_rows(container) == 1
    assert _artifact_dirs(container) == [run.id]
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert any(e.edge_kind.value == "solved-by" for e in neighbors.neighbors)
