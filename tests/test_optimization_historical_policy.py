"""Historical-policy verification + non-finite objective guards (fourth review, High #4)."""

from __future__ import annotations

import math

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization import policy as policy_mod
from orbitmind.optimization.benchmark import conclude, proven_optimum
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    QuantumExperiment,
    QuantumSampleResult,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.policy import (
    ComparisonPolicy,
    authenticate_policy_with_snapshot,
    default_policy,
    get_policy,
    policy_checksum,
)
from orbitmind.optimization.verification import verify_benchmark

_THRESHOLDS = default_policy().thresholds()


# ---- historical policy authentication (no active-registry dependency) -------------------
def test_retired_policy_authenticates_against_self_consistent_snapshot() -> None:
    pol = get_policy("lenient-v1")
    assert pol is not None
    snapshot = pol.model_dump(mode="json")
    # Simulate a registry without this policy (retired) -> snapshot path, no KeyError/crash.
    result, ok, _msg = authenticate_policy_with_snapshot(
        policy_id="lenient-v1",
        policy_version=pol.policy_version,
        policy_checksum_value=pol.checksum,
        thresholds=pol.thresholds(),
        snapshot=snapshot,
    )
    assert ok and result is not None and result.policy_id == "lenient-v1"


def test_retired_policy_without_snapshot_fails_closed_no_crash() -> None:
    result, ok, _msg = authenticate_policy_with_snapshot(
        policy_id="ghost-v9",
        policy_version="1",
        policy_checksum_value="deadbeef",
        thresholds=_THRESHOLDS,
        snapshot=None,
    )
    assert result is None and not ok  # honest failure, not an exception


def test_retired_policy_with_mismatched_claim_fails() -> None:
    # A retired (non-registry) policy with a self-consistent snapshot, but the CLAIMED version
    # disagrees with the snapshot -> fail closed.
    ghost = ComparisonPolicy(
        policy_id="archived-v1",
        policy_version="1",
        competitive_relative_gap=0.1,
        min_feasible_sample_ratio=0.2,
    )
    ghost = ghost.model_copy(update={"checksum": policy_checksum(ghost)})
    _result, ok, _msg = authenticate_policy_with_snapshot(
        policy_id="archived-v1",
        policy_version="WRONG",  # disagrees with the snapshot's version
        policy_checksum_value=ghost.checksum,
        thresholds=ghost.thresholds(),
        snapshot=ghost.model_dump(mode="json"),
    )
    assert not ok


def test_verify_benchmark_survives_policy_retirement(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, findings = svc.benchmark(problem.id, seed=7, run_quantum=False, policy_id="lenient-v1")
    assert all(f.passed for f in findings)
    stored = svc.get_problem(problem.id)
    assert stored is not None
    # Retire lenient-v1 from the active registry (controlled retirement).
    pruned = {k: v for k, v in policy_mod._REGISTRY.items() if k != "lenient-v1"}
    monkeypatch.setattr(policy_mod, "_REGISTRY", pruned)
    findings2 = verify_benchmark(stored, run)
    policy_finding = next(f for f in findings2 if f.check_id == "opt.policy_authenticated")
    assert policy_finding.passed  # still verifiable via the historical snapshot, no crash


# ---- non-finite objective guards in the pure policy -------------------------------------
def _exact(obj: float | None, *, optimal: bool = True, feasible: bool = True) -> SolverResult:
    from orbitmind.optimization.models import CandidateSchedule

    schedule = (
        CandidateSchedule(problem_checksum="x", selected_opportunity_ids=()) if feasible else None
    )
    return SolverResult(
        problem_checksum="x",
        solver_kind=SolverKind.EXACT,
        solver_name="exact",
        solver_version="1",
        status=ExperimentStatus.COMPLETED,
        optimality_status=OptimalityStatus.OPTIMAL if optimal else OptimalityStatus.FEASIBLE,
        objective_value=obj,
        feasible=feasible,
        seed=1,
        runtime_seconds=0.0,
        configuration=SolverConfiguration(solver_kind=SolverKind.EXACT, seed=1),
        schedule=schedule,
    )


def test_non_finite_exact_objective_is_not_a_known_optimum() -> None:
    assert proven_optimum(_exact(math.inf)) == (None, None)
    assert proven_optimum(_exact(math.nan)) == (None, None)
    assert proven_optimum(_exact(5.0))[0] == 5.0  # a finite optimum still resolves


def _quantum(obj: float, ratio: float) -> QuantumExperiment:
    from orbitmind.optimization.models import QuantumCircuitMetadata

    meta = QuantumCircuitMetadata(
        qubits=4,
        depth=3,
        gate_counts={"h": 4},
        shots=8,
        optimizer_iterations=1,
        qaoa_layers=1,
        simulator_backend="AerSimulator",
        transpile_level=1,
        seed_simulator=7,
        seed_transpiler=7,
    )
    sample = QuantumSampleResult(
        bitstring="0000",
        count=8,
        probability=1.0,
        feasible=True,
        raw_mission_value=0.0,
        objective_value=obj,
        qubo_energy=0.0,
        violations_count=0,
    )
    return QuantumExperiment(
        problem_checksum="x",
        status=ExperimentStatus.COMPLETED,
        configuration=SolverConfiguration(solver_kind=SolverKind.QUANTUM_QAOA, seed=7, shots=8),
        circuit_metadata=meta,
        samples=[sample],
        total_shots=8,
        feasible_sample_ratio=ratio,
        best_feasible_sample=sample,
        execution_nonce="a" * 32,
    )


def test_non_finite_quantum_objective_is_non_positive() -> None:
    # A non-finite quantum sample objective is malformed auxiliary evidence and is rejected up
    # front (fifth review, Medium #3) — never a positive conclusion.
    conclusion, _ = conclude(
        exact_result=_exact(5.0),
        greedy_result=None,
        quantum_experiment=_quantum(math.inf, 1.0),
        thresholds=_THRESHOLDS,
    )
    assert conclusion.value == "insufficient-evidence"


def test_out_of_range_feasible_ratio_is_insufficient() -> None:
    conclusion, _ = conclude(
        exact_result=_exact(5.0),
        greedy_result=None,
        quantum_experiment=_quantum(4.0, 1.5),  # ratio outside [0, 1]
        thresholds=_THRESHOLDS,
    )
    assert conclusion.value == "insufficient-evidence"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_malformed_known_optimum_blocks_positive_conclusion(bad: float) -> None:
    # A valid quantum objective + a malformed known optimum must NOT yield a positive conclusion.
    exact = _exact(5.0).model_copy(update={"known_optimum": bad})
    conclusion, rationale = conclude(
        exact_result=exact,
        greedy_result=None,
        quantum_experiment=_quantum(4.0, 1.0),
        thresholds=_THRESHOLDS,
    )
    assert conclusion.value == "insufficient-evidence"
    assert "malformed auxiliary evidence" in rationale


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_malformed_objective_gap_blocks_positive_conclusion(bad: float) -> None:
    q = _quantum(4.0, 1.0).model_copy(update={"objective_gap": bad})
    conclusion, _ = conclude(
        exact_result=_exact(5.0), greedy_result=None, quantum_experiment=q, thresholds=_THRESHOLDS
    )
    assert conclusion.value == "insufficient-evidence"


def test_valid_zero_values_are_accepted() -> None:
    # Zero is a valid finite value, not malformed.
    conclusion, _ = conclude(
        exact_result=_exact(0.0),
        greedy_result=None,
        quantum_experiment=None,
        thresholds=_THRESHOLDS,
    )
    assert conclusion.value == "classical-exact-best"
