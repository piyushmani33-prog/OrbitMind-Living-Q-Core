"""Atomic evidence release: accepted state + memory edges gated on verification (finding #23).

A benchmark is persisted with an accepted flag (benchmark_runs.verification_passed) only when
verification passes; on failure it is retained as an audit record in the unaccepted state with
no positive scientific-memory edges.
"""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import ComparisonConclusion
from orbitmind.optimization.verification import verify_benchmark
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository
from orbitmind.verification.models import (
    CheckCategory,
    FindingStatus,
    Severity,
    VerificationFinding,
)


def _accepted(container: AppContainer, benchmark_id: str) -> bool:
    session = container.database.session()
    row = SqlAlchemyOptimizationRepository(session).get_benchmark(benchmark_id)
    session.close()
    assert row is not None
    return bool(row.verification_passed)


def test_verified_benchmark_is_accepted_with_memory_edges(container: AppContainer) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    assert _accepted(container, run.id) is True
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert any(e.edge_kind.value == "solved-by" for e in neighbors.neighbors)


def test_failed_verification_leaves_unaccepted_record_and_no_memory(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))

    def _inject(*a: object, **k: object) -> list[VerificationFinding]:
        return [
            *verify_benchmark(*a, **k),  # type: ignore[arg-type]
            VerificationFinding(
                check_id="opt.injected_failure",
                severity=Severity.CRITICAL,
                status=FindingStatus.FAILED,
                explanation="injected",
                category=CheckCategory.POLICY,
            ),
        ]

    monkeypatch.setattr("orbitmind.optimization.service.verify_benchmark", _inject)
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)

    # Persisted as an audit record but NOT accepted, and never positively concluded.
    assert _accepted(container, run.id) is False
    assert run.comparison is not None
    assert run.comparison.conclusion == ComparisonConclusion.INSUFFICIENT_EVIDENCE
    # No positive scientific-memory edges for an unverified benchmark.
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert neighbors.neighbors == []
