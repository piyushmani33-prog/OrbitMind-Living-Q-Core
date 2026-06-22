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


def _cleanup_failed_audits(container: AppContainer) -> int:
    return _count(
        container,
        "SELECT count(*) FROM audit_events WHERE action='optimization.benchmark_failed' "
        "AND detail::text LIKE '%artifact_cleanup_failed%'"
        if container.database.is_postgres
        else "SELECT count(*) FROM audit_events WHERE action='optimization.benchmark_failed' "
        "AND detail LIKE '%artifact_cleanup_failed%'",
    )


def test_construction_failure_before_persistence_is_audited(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The failure boundary covers construction, not just post-construction stages (Medium #3).
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    monkeypatch.setattr(
        "orbitmind.optimization.service.run_benchmark",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom-construct")),
    )
    with pytest.raises(RuntimeError):
        container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    assert _benchmark_rows(container) == 0
    assert _failure_audits(container) >= 1


def test_policy_resolution_failure_is_audited(
    container: AppContainer,
) -> None:
    # An unknown policy id fails during policy-resolution, still inside the audit boundary.
    from orbitmind.core.errors import ValidationError

    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    with pytest.raises(ValidationError):
        container.optimization_service.benchmark(
            problem.id, seed=7, run_quantum=False, policy_id="no-such-policy"
        )
    assert _failure_audits(container) >= 1


def test_cleanup_failure_does_not_mask_original_error(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    svc = container.optimization_service
    _inject(container, monkeypatch, "persistence")  # original failure
    monkeypatch.setattr(
        svc._viz, "cleanup", lambda *a, **k: (_ for _ in ()).throw(OSError("boom-cleanup"))
    )
    with pytest.raises(RuntimeError, match="boom-persist"):  # ORIGINAL error, not the cleanup one
        svc.benchmark(problem.id, seed=7, run_quantum=False, generate_artifacts=True)
    assert _cleanup_failed_audits(container) >= 1  # cleanup failure recorded separately


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
