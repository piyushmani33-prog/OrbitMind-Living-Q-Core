"""Scientific metadata (caveats + epistemic labels) is receipt-bound immutable evidence.

Final acceptance — Critical 2: changing any limitations / rationale / epistemic status /
conclusion after acceptance must invalidate read authentication, even when the replacement text
is benign (not an overclaim).
"""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_models import (
    BenchmarkComparisonRow,
    SolverRunRow,
)


def _accepted(container: AppContainer) -> str:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    assert container.optimization_service.read_benchmark_evidence(run.id).authenticated
    return run.id


def test_benign_comparison_limitations_replacement_fails(container: AppContainer) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    row.limitations = "small test run"  # benign, NOT an overclaim
    session.commit()
    session.close()
    auth = container.optimization_service.read_benchmark_evidence(bid)
    assert auth.integrity_failed and not auth.authenticated


def test_benign_comparison_rationale_replacement_fails(container: AppContainer) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    row.rationale = "rewritten rationale"
    session.commit()
    session.close()
    assert container.optimization_service.read_benchmark_evidence(bid).integrity_failed


def test_epistemic_status_downgrade_fails(container: AppContainer) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    row.epistemic_status = "verified-fact"  # forbidden upgrade of the epistemic label
    session.commit()
    session.close()
    assert container.optimization_service.read_benchmark_evidence(bid).integrity_failed


def test_conclusion_field_replacement_fails(container: AppContainer) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    row.conclusion = "quantum-competitive"
    session.commit()
    session.close()
    assert container.optimization_service.read_benchmark_evidence(bid).integrity_failed


def test_benign_solver_limitations_replacement_fails(container: AppContainer) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(SolverRunRow).filter_by(benchmark_id=bid, solver_kind="exact").first()
    blob = dict(row.result_json)
    blob["limitations"] = "trivial instance"  # benign change to a caveat
    row.result_json = blob
    session.commit()
    session.close()
    assert container.optimization_service.read_benchmark_evidence(bid).integrity_failed


@pytest.mark.parametrize(
    "field",
    ["limitations", "rationale"],
)
def test_overclaim_text_fails_in_each_comparison_field(container: AppContainer, field: str) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    setattr(row, field, "quantum advantage verified on this instance")
    session.commit()
    session.close()
    assert container.optimization_service.read_benchmark_evidence(bid).integrity_failed
