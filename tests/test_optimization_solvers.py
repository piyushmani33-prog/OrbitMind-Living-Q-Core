"""Unit tests: exact + greedy classical solvers."""

from __future__ import annotations

import pytest

from orbitmind.optimization import fixtures
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    SolverConfiguration,
    SolverKind,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.solvers import solve_exact, solve_greedy

_OPTIMA = {"default": 10.0, "resource-bound": 15.0, "mutual-exclusion": 10.0}


@pytest.mark.parametrize("name,optimum", _OPTIMA.items())
def test_exact_finds_proven_optimum(name: str, optimum: float) -> None:
    p = normalize_problem(fixtures.fixture(name))
    result = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT))
    assert result.status == ExperimentStatus.COMPLETED
    assert result.optimality_status == OptimalityStatus.OPTIMAL
    assert result.feasible and result.objective_value == optimum
    # Independent re-evaluation agrees.
    ev = Evaluator(p)
    assert ev.evaluate(set(result.schedule.selected_opportunity_ids)).feasible


def test_exact_is_deterministic() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    a = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT))
    b = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT))
    assert a.schedule.selected_opportunity_ids == b.schedule.selected_opportunity_ids


def test_exact_unsupported_when_too_large() -> None:
    p = fixtures.fixture("default")
    p = p.model_copy(update={"limits": p.limits.model_copy(update={"exact_max_variables": 3})})
    p = normalize_problem(p)
    result = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT))
    assert result.status == ExperimentStatus.UNSUPPORTED
    assert result.schedule is None


@pytest.mark.parametrize("name,optimum", _OPTIMA.items())
def test_greedy_is_feasible_and_deterministic(name: str, optimum: float) -> None:
    p = normalize_problem(fixtures.fixture(name))
    a = solve_greedy(p, SolverConfiguration(solver_kind=SolverKind.GREEDY))
    b = solve_greedy(p, SolverConfiguration(solver_kind=SolverKind.GREEDY))
    assert a.feasible
    assert a.schedule.selected_opportunity_ids == b.schedule.selected_opportunity_ids
    assert a.objective_value is not None and a.objective_value <= optimum  # never beats exact


def test_greedy_respects_mandatory() -> None:
    p = normalize_problem(fixtures.fixture("resource-bound"))
    result = solve_greedy(p, SolverConfiguration(solver_kind=SolverKind.GREEDY))
    assert "OPP-4" in result.schedule.selected_opportunity_ids  # mandatory


def test_exact_timeout_returns_feasible_not_optimal() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    result = solve_exact(p, SolverConfiguration(solver_kind=SolverKind.EXACT, timeout_seconds=1e-9))
    # Either it finished the tiny instance, or it timed out with a feasible (not proven) result.
    assert result.status in (ExperimentStatus.COMPLETED, ExperimentStatus.TIMED_OUT)
    if result.status == ExperimentStatus.TIMED_OUT:
        assert result.optimality_status != OptimalityStatus.OPTIMAL
