"""Unit tests: problem normalization, evaluation, QUBO equivalence, bit order."""

from __future__ import annotations

from itertools import product

import pytest

from orbitmind.core.errors import ValidationError
from orbitmind.optimization import fixtures
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import ConstraintKind
from orbitmind.optimization.penalties import penalty_is_sufficient
from orbitmind.optimization.problem import (
    generate_conflicts,
    normalize_problem,
    problem_checksum,
    resolved_penalty,
    variable_order,
)
from orbitmind.optimization.qubo import build_qubo, qubo_energy, qubo_to_ising

_NAMES = ("default", "resource-bound", "mutual-exclusion")


def test_normalize_stamps_deterministic_checksum() -> None:
    p1 = normalize_problem(fixtures.fixture("default"))
    p2 = normalize_problem(fixtures.fixture("default"))
    assert p1.checksum and p1.checksum == p2.checksum
    assert p1.checksum == problem_checksum(p1)


def test_normalize_rejects_bad_problems() -> None:
    p = fixtures.fixture("default")
    dup = p.model_copy(update={"opportunities": [p.opportunities[0], p.opportunities[0]]})
    with pytest.raises(ValidationError):
        normalize_problem(dup)
    bad = p.model_copy(
        update={"constraints": p.constraints.model_copy(update={"mandatory": ("NOPE",)})}
    )
    with pytest.raises(ValidationError):
        normalize_problem(bad)


def test_variable_order_is_sorted_and_stable() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    order = variable_order(p)
    assert order == tuple(sorted(order))
    assert list(order) == ["OPP-1", "OPP-2", "OPP-3", "OPP-4"]


def test_conflict_generation() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    conflicts = generate_conflicts(p)
    pairs = {(c.opportunity_a, c.opportunity_b, c.kind) for c in conflicts}
    assert ("OPP-1", "OPP-2", ConstraintKind.NO_OVERLAP) in pairs
    assert ("OPP-3", "OPP-4", ConstraintKind.NO_OVERLAP) in pairs

    mx = normalize_problem(fixtures.fixture("mutual-exclusion"))
    assert any(c.kind == ConstraintKind.MUTUAL_EXCLUSION for c in generate_conflicts(mx))


def test_evaluator_detects_each_violation_kind() -> None:
    p = normalize_problem(fixtures.fixture("resource-bound"))
    ev = Evaluator(p)
    # Select a per-target-limit + capacity violating set.
    bad = ev.evaluate({"OPP-1", "OPP-2", "OPP-3", "OPP-4"})
    kinds = {v.kind for v in bad.violations}
    assert ConstraintKind.MAX_OBSERVATIONS in kinds  # 4 > 3
    assert ConstraintKind.PER_TARGET_LIMIT in kinds  # T1 twice
    assert not bad.feasible

    missing_mandatory = ev.evaluate({"OPP-1"})  # OPP-4 mandatory missing
    assert any(v.kind == ConstraintKind.MANDATORY for v in missing_mandatory.violations)


def test_objective_and_penalty_decomposition() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    ev = Evaluator(p)
    feasible = ev.evaluate({"OPP-2", "OPP-3"})
    assert feasible.feasible
    assert feasible.raw_mission_value == 10.0
    assert feasible.constraint_penalty == 0.0
    assert feasible.penalized_objective == 10.0
    conflict = ev.evaluate({"OPP-1", "OPP-2"})  # overlap -> penalized
    assert conflict.constraint_penalty == resolved_penalty(p)
    assert conflict.penalized_objective == conflict.raw_mission_value - conflict.constraint_penalty


def test_penalty_is_sufficient() -> None:
    assert penalty_is_sufficient(normalize_problem(fixtures.fixture("default")))


@pytest.mark.parametrize("name", _NAMES)
def test_qubo_energy_equals_negated_penalized_objective_exhaustive(name: str) -> None:
    """CRITICAL: QUBO energy == -penalized_objective for ALL bitstrings (mismatch = failure)."""
    p = normalize_problem(fixtures.fixture(name))
    ev = Evaluator(p)
    qubo = build_qubo(p)
    assert qubo.variable_opportunities == variable_order(p)  # bit-order convention
    for bits_t in product("01", repeat=qubo.num_vars):
        bits = "".join(bits_t)
        assert abs(qubo_energy(qubo, bits) + ev.evaluate_bitstring(bits).penalized_objective) < 1e-9


@pytest.mark.parametrize("name", _NAMES)
def test_ising_roundtrip(name: str) -> None:
    p = normalize_problem(fixtures.fixture(name))
    qubo = build_qubo(p)
    h, j_coeffs, offset = qubo_to_ising(qubo)
    n = qubo.num_vars
    for bits_t in product("01", repeat=n):
        bits = "".join(bits_t)
        z = [1 - 2 * int(b) for b in bits]  # x=1 -> z=-1
        energy = offset + sum(h.get(i, 0.0) * z[i] for i in range(n))
        energy += sum(c * z[i] * z[j] for (i, j), c in j_coeffs.items())
        assert abs(energy - qubo_energy(qubo, bits)) < 1e-9


def test_qubo_checksum_is_deterministic() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    assert build_qubo(p).checksum == build_qubo(p).checksum


def test_bitstring_decoding_uses_index_order() -> None:
    p = normalize_problem(fixtures.fixture("default"))
    ev = Evaluator(p)
    # index 0 = OPP-1, index 2 = OPP-3 -> "1010" selects OPP-1 + OPP-3
    decoded = ev.evaluate_bitstring("1010")
    assert decoded.selected_opportunity_ids == ("OPP-1", "OPP-3")
