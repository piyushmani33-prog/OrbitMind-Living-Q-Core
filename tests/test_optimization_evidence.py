"""Authoritative quantum evidence manifest + release gate (High finding #1).

Coordinated, internally-consistent evidence/sample forgeries must FAIL verification, and a
benchmark that fails the release gate must not retain a positive conclusion or create any
scientific-memory edges (the complete service path, not just helpers).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.evidence import build_evidence_manifest, evidence_matches_manifest
from orbitmind.optimization.models import (
    BenchmarkRun,
    ComparisonConclusion,
    QuantumExperiment,
    SolverConfiguration,
    SolverKind,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.verification import (
    all_critical_passed,
    benchmark_verified_for_evidence,
    verify_benchmark,
)
from orbitmind.quantum.adapter import quantum_available
from orbitmind.verification.models import (
    CheckCategory,
    FindingStatus,
    Severity,
    VerificationFinding,
)

_PROBLEM = normalize_problem(fixtures.fixture("default"))


# --------------------------------------------------------------------------------------------
# Manifest unit checks (no Aer): the manifest is server-derived and self-consistent.
# --------------------------------------------------------------------------------------------
def test_manifest_is_self_consistent_and_detects_field_tampering() -> None:
    config = SolverConfiguration(solver_kind=SolverKind.QUANTUM_QAOA, seed=7, shots=64)
    manifest = build_evidence_manifest(_PROBLEM, config)
    ok, _ = evidence_matches_manifest(manifest, manifest)
    assert ok
    for field, value in [
        ("qubo_checksum", "deadbeef"),
        ("variable_mapping", ("X", "Y", "Z", "W")),
        ("penalty_value", manifest.penalty_value + 1.0),
        ("penalty_proof_status", "unproven"),
        ("simulator_backend", "IBMQ"),
        ("bit_order", "tampered"),
        ("seeds", {"seed": 1, "seed_simulator": 1, "seed_transpiler": 1}),
        ("software_versions", {"qiskit": "0.0", "qiskit-aer": "0.0"}),
        ("manifest_checksum", "00"),
    ]:
        forged = manifest.model_copy(update={field: value})
        matched, _reason = evidence_matches_manifest(forged, manifest)
        assert not matched, f"tampering {field} should be detected"


# --------------------------------------------------------------------------------------------
# Release gate via the COMPLETE service path (no Aer required).
# --------------------------------------------------------------------------------------------
def _failing_finding() -> VerificationFinding:
    return VerificationFinding(
        check_id="opt.quantum_evidence_authentic",
        severity=Severity.CRITICAL,
        status=FindingStatus.FAILED,
        explanation="injected coordinated tamper",
        category=CheckCategory.POLICY,
    )


def test_release_gate_blocks_memory_and_downgrades_conclusion(
    container: AppContainer, monkeypatch: pytest.MonkeyPatch
) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))

    def _verify_with_injected_failure(*_a: object, **_k: object) -> list[VerificationFinding]:
        real = verify_benchmark(*_a, **_k)  # type: ignore[arg-type]
        return [*real, _failing_finding()]

    monkeypatch.setattr(
        "orbitmind.optimization.service.verify_benchmark", _verify_with_injected_failure
    )
    run, findings = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)

    assert not benchmark_verified_for_evidence(findings)
    # Conclusion downgraded to non-positive; never a positive/competitive claim.
    assert run.comparison is not None
    assert run.comparison.conclusion == ComparisonConclusion.INSUFFICIENT_EVIDENCE
    # No scientific-memory edges created for an unverified benchmark.
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert neighbors.neighbors == []


def test_release_gate_allows_memory_when_verified(container: AppContainer) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    _run, findings = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    assert benchmark_verified_for_evidence(findings)
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert any(e.edge_kind.value == "solved-by" for e in neighbors.neighbors)


# --------------------------------------------------------------------------------------------
# Coordinated evidence/sample tampering on a REAL Aer experiment must fail verification.
# --------------------------------------------------------------------------------------------
pytestmark_quantum = pytest.mark.skipif(
    not quantum_available(), reason="qiskit/qiskit-aer not installed"
)


@pytest.fixture(scope="module")
def quantum_run() -> BenchmarkRun:
    return run_benchmark(_PROBLEM, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)


def _qexp(run: BenchmarkRun) -> QuantumExperiment:
    assert run.quantum_experiment is not None
    return run.quantum_experiment


def _with_qexp(run: BenchmarkRun, qexp: QuantumExperiment) -> BenchmarkRun:
    return run.model_copy(update={"quantum_experiment": qexp})


def _tamper_evidence(field: str, value: object) -> Callable[[BenchmarkRun], BenchmarkRun]:
    def _apply(run: BenchmarkRun) -> BenchmarkRun:
        q = _qexp(run)
        assert q.evidence is not None
        return _with_qexp(
            run, q.model_copy(update={"evidence": q.evidence.model_copy(update={field: value})})
        )

    return _apply


def _double_counts_and_total(run: BenchmarkRun) -> BenchmarkRun:
    q = _qexp(run)
    samples = [s.model_copy(update={"count": s.count * 2}) for s in q.samples]
    return _with_qexp(
        run, q.model_copy(update={"samples": samples, "total_shots": q.total_shots * 2})
    )


def _negative_count(run: BenchmarkRun) -> BenchmarkRun:
    q = _qexp(run)
    samples = [*q.samples]
    samples[0] = samples[0].model_copy(update={"count": -5})
    return _with_qexp(run, q.model_copy(update={"samples": samples}))


def _duplicate_sample(run: BenchmarkRun) -> BenchmarkRun:
    q = _qexp(run)
    samples = [*q.samples, q.samples[0]]
    return _with_qexp(run, q.model_copy(update={"samples": samples}))


def _malformed_bitstring(run: BenchmarkRun) -> BenchmarkRun:
    q = _qexp(run)
    samples = [*q.samples]
    samples[0] = samples[0].model_copy(update={"bitstring": "2X01"})
    return _with_qexp(run, q.model_copy(update={"samples": samples}))


@pytestmark_quantum
def test_untampered_quantum_run_verifies(quantum_run: BenchmarkRun) -> None:
    assert all_critical_passed(verify_benchmark(_PROBLEM, quantum_run))


_EVIDENCE_TAMPERS = [
    ("qubo_checksum", _tamper_evidence("qubo_checksum", "deadbeef")),
    ("variable_mapping", _tamper_evidence("variable_mapping", ("A", "B", "C", "D"))),
    ("penalty_value", _tamper_evidence("penalty_value", 999.0)),
    ("penalty_proof_status", _tamper_evidence("penalty_proof_status", "unproven")),
    ("simulator_backend", _tamper_evidence("simulator_backend", "IBMQ")),
    ("bit_order", _tamper_evidence("bit_order", "forged")),
    ("manifest_checksum", _tamper_evidence("manifest_checksum", "00")),
    ("double_counts_and_total", _double_counts_and_total),
    ("negative_count", _negative_count),
    ("duplicate_sample", _duplicate_sample),
    ("malformed_bitstring", _malformed_bitstring),
]


@pytestmark_quantum
@pytest.mark.parametrize("name,tamper", _EVIDENCE_TAMPERS, ids=[n for n, _ in _EVIDENCE_TAMPERS])
def test_coordinated_quantum_tampering_fails(
    quantum_run: BenchmarkRun, name: str, tamper: Callable[[BenchmarkRun], BenchmarkRun]
) -> None:
    tampered = tamper(quantum_run)
    assert not all_critical_passed(verify_benchmark(_PROBLEM, tampered)), name
