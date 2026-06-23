"""Penalty proof-status + pre-execution gate (second Codex review, High finding #4).

The QUBO penalty carries an explicit proof status; contradictory/unsafe/unproven penalties
must never be reported sufficient and must never reach Aer. The analytic satisfiability
check works for sizes beyond exhaustive enumeration (n > 16).
"""

from __future__ import annotations

import datetime as dt

import pytest

from orbitmind.optimization import quantum as quantum_mod
from orbitmind.optimization.models import (
    ConstraintSet,
    ExperimentStatus,
    ObservationOpportunity,
    ObservationTarget,
    PenaltyProofStatus,
    SatelliteResource,
    SchedulingObjective,
    SchedulingProblem,
    SchedulingProblemLimits,
    SolverConfiguration,
    SolverKind,
    TimeWindow,
)
from orbitmind.optimization.penalties import penalty_policy, proof_allows_execution
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.quantum import run_quantum_experiment

_B = dt.datetime(2026, 6, 21, 10, 0, 0, tzinfo=dt.UTC)


def _win(a: int, b: int) -> TimeWindow:
    return TimeWindow(start=_B + dt.timedelta(minutes=a), end=_B + dt.timedelta(minutes=b))


def _problem(
    n: int,
    *,
    mandatory: tuple[str, ...] = (),
    mutually_exclusive: tuple[tuple[str, str], ...] = (),
    penalty: float | None = None,
    same_satellite: bool = False,
) -> SchedulingProblem:
    """n opportunities; each on its own satellite (no incidental overlaps) unless requested."""
    opps = []
    sats = []
    seen_sats = set()
    for i in range(n):
        sat = "SAT-0" if same_satellite else f"SAT-{i:02d}"
        opps.append(
            ObservationOpportunity(
                id=f"OPP-{i:02d}",
                satellite_id=sat,
                target_id="T1",
                window=_win(0, 30),
                mission_value=5.0,
                duration_seconds=1800.0,
                energy_cost=1.0,
                storage_cost=1.0,
            )
        )
        if sat not in seen_sats:
            sats.append(SatelliteResource(id=sat, energy_capacity=1000.0, storage_capacity=1000.0))
            seen_sats.add(sat)
    return normalize_problem(
        SchedulingProblem(
            name=f"p{n}",
            opportunities=opps,
            satellites=sats,
            targets=[ObservationTarget(id="T1")],
            constraints=ConstraintSet(
                mandatory=mandatory,
                mutually_exclusive=mutually_exclusive,
                enforce_no_overlap=not same_satellite,
            ),
            objective=SchedulingObjective(penalty_coefficient=penalty),
            limits=SchedulingProblemLimits(max_variables=20, exact_max_variables=20),
        )
    )


def test_large_mandatory_contradiction_is_detected_analytically() -> None:
    # 17 variables: two mutually-exclusive mandatory opportunities -> contradictory (n>16).
    p = _problem(17, mandatory=("OPP-00", "OPP-01"), mutually_exclusive=(("OPP-00", "OPP-01"),))
    policy = penalty_policy(p)
    assert policy.proof_status == PenaltyProofStatus.CONTRADICTORY
    assert policy.satisfying_encoded_assignment_exists is False
    assert policy.sufficient is False


def test_large_satisfiable_problem_is_proven_sufficient() -> None:
    p = _problem(17, mandatory=("OPP-00", "OPP-01"))  # auto penalty, no conflicting mandatory
    policy = penalty_policy(p)
    assert policy.proof_status == PenaltyProofStatus.PROVEN_SUFFICIENT
    assert policy.sufficient is True


def test_multiple_mandatory_conflicts_are_contradictory() -> None:
    p = _problem(
        5,
        mandatory=("OPP-00", "OPP-01", "OPP-02"),
        mutually_exclusive=(("OPP-00", "OPP-01"), ("OPP-01", "OPP-02")),
    )
    assert penalty_policy(p).proof_status == PenaltyProofStatus.CONTRADICTORY


def test_unsafe_tiny_custom_penalty_is_proven_unsafe() -> None:
    # Two same-satellite overlapping opps -> a conflict pair; penalty too small to dominate.
    p = _problem(2, same_satellite=True, mutually_exclusive=(("OPP-00", "OPP-01"),), penalty=1.0)
    assert penalty_policy(p).proof_status == PenaltyProofStatus.PROVEN_UNSAFE


def test_unproven_large_custom_penalty() -> None:
    # n>16 with a small custom penalty (<= bound): cannot prove sufficiency cheaply.
    p = _problem(17, mutually_exclusive=(("OPP-00", "OPP-01"),), penalty=1.0)
    assert penalty_policy(p).proof_status == PenaltyProofStatus.UNPROVEN
    assert penalty_policy(p).sufficient is False


def test_negative_penalty_is_proven_unsafe() -> None:
    # A negative explicit penalty is rejected by resolved_penalty; the policy reports unsafe.
    p = _problem(3, mutually_exclusive=(("OPP-00", "OPP-01"),))
    bad = p.model_copy(update={"objective": SchedulingObjective(penalty_coefficient=-1.0)})
    assert penalty_policy(bad).proof_status == PenaltyProofStatus.PROVEN_UNSAFE


def test_automatic_penalty_has_analytic_proof() -> None:
    p = _problem(17, mutually_exclusive=(("OPP-00", "OPP-01"),))  # auto penalty
    policy = penalty_policy(p)
    assert policy.proof_status == PenaltyProofStatus.PROVEN_SUFFICIENT
    assert policy.method == "analytical-bound"
    assert policy.penalty > policy.total_weighted_value_bound


@pytest.mark.parametrize(
    "status",
    [
        PenaltyProofStatus.CONTRADICTORY,
        PenaltyProofStatus.PROVEN_UNSAFE,
        PenaltyProofStatus.UNPROVEN,
    ],
)
def test_proof_allows_execution_only_for_safe_statuses(status: PenaltyProofStatus) -> None:
    assert proof_allows_execution(status) is False
    assert proof_allows_execution(PenaltyProofStatus.PROVEN_SUFFICIENT) is True
    assert proof_allows_execution(PenaltyProofStatus.NOT_APPLICABLE) is True


def test_unsafe_penalty_never_invokes_aer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-execution gate must return BEFORE spawning the Aer worker (no QUBO run)."""
    p = _problem(17, mandatory=("OPP-00", "OPP-01"), mutually_exclusive=(("OPP-00", "OPP-01"),))
    monkeypatch.setattr(quantum_mod, "quantum_available", lambda: True)  # pretend Aer present

    def _spawned(*_a: object, **_k: object) -> object:
        raise AssertionError("Aer worker was spawned despite a non-executable penalty proof")

    monkeypatch.setattr(quantum_mod.mp, "get_context", _spawned)
    config = SolverConfiguration(solver_kind=SolverKind.QUANTUM_QAOA, seed=7, timeout_seconds=5.0)
    result = run_quantum_experiment(p, config)
    assert result.status == ExperimentStatus.INCONCLUSIVE
    assert result.circuit_metadata is None
    assert result.best_feasible_sample is None
    assert "contradictory" in result.error
