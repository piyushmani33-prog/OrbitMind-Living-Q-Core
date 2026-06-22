"""Persisted policy thresholds never default to trusted values (final acceptance, High #2)."""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.persistence.optimization_models import BenchmarkComparisonRow
from orbitmind.persistence.optimization_repository import PersistedBenchmarkThresholds


def _accepted(container: AppContainer) -> str:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    assert container.optimization_service.read_benchmark_evidence(run.id).authenticated
    return run.id


@pytest.mark.parametrize(
    "thresholds_json",
    [
        {},  # empty object: must NOT default to trusted strict-v1 thresholds
        {"competitive_relative_gap": 0.0},  # partial (missing ratio)
        {"min_feasible_sample_ratio": 0.05},  # partial (missing gap)
        {"competitive_relative_gap": 0.0, "min_feasible_sample_ratio": 0.05, "extra": 1},  # extra
        {"competitive_relative_gap": "x", "min_feasible_sample_ratio": 0.05},  # wrong type
        {"competitive_relative_gap": float("inf"), "min_feasible_sample_ratio": 0.05},  # non-finite
        {"competitive_relative_gap": 2.0, "min_feasible_sample_ratio": 0.05},  # out of range
    ],
)
def test_malformed_persisted_thresholds_fail_closed(
    container: AppContainer, thresholds_json: dict
) -> None:
    bid = _accepted(container)
    session = container.database.session()
    row = session.query(BenchmarkComparisonRow).filter_by(benchmark_id=bid).first()
    row.thresholds_json = thresholds_json
    session.commit()
    session.close()
    auth = container.optimization_service.read_benchmark_evidence(bid)
    assert auth.found and auth.integrity_failed and auth.run is None
    assert auth.integrity_status == "malformed-persisted-evidence"


def test_strict_dto_rejects_each_malformed_input() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PersistedBenchmarkThresholds.model_validate({})
    with pytest.raises(ValidationError):
        PersistedBenchmarkThresholds.model_validate({"competitive_relative_gap": 0.0})
    with pytest.raises(ValidationError):
        PersistedBenchmarkThresholds.model_validate(
            {"competitive_relative_gap": float("nan"), "min_feasible_sample_ratio": 0.05}
        )
    # A complete, in-range pair is accepted.
    ok = PersistedBenchmarkThresholds.model_validate(
        {"competitive_relative_gap": 0.25, "min_feasible_sample_ratio": 0.33}
    )
    assert ok.competitive_relative_gap == 0.25
