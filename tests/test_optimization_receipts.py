"""Signed execution receipts: receipt attacks + full service-path acceptance (High #1)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.models import BenchmarkRun, SolverKind
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.receipts import (
    BenchmarkExecutionReceipt,
    HmacSha256EvidenceReceiptSigner,
    build_receipt,
    verify_receipt,
)
from orbitmind.optimization.service import OptimizationService

_PROBLEM = normalize_problem(fixtures.fixture("default"))
_SIGNER = HmacSha256EvidenceReceiptSigner(b"unit-test-secret", "unit-key")
_SIGNERS = {"unit-key": _SIGNER}


def _run() -> BenchmarkRun:
    return run_benchmark(_PROBLEM, seed=7, run_quantum=False)


def test_untampered_receipt_verifies() -> None:
    run = _run()
    receipt = build_receipt(run, signer=_SIGNER)
    assert verify_receipt(receipt, run=run, signers=_SIGNERS).ok


# ---- receipt attacks -----------------------------------------------------------------------
def _changed_signature(
    r: BenchmarkExecutionReceipt, run: BenchmarkRun
) -> BenchmarkExecutionReceipt:
    return r.model_copy(update={"signature": "00" * 32})


def _changed_payload(r: BenchmarkExecutionReceipt, run: BenchmarkRun) -> BenchmarkExecutionReceipt:
    return r.model_copy(update={"payload": r.payload.model_copy(update={"problem_checksum": "x"})})


_RECEIPT_ATTACKS: list[tuple[str, Callable]] = [
    ("changed_signature", _changed_signature),
    ("changed_payload", _changed_payload),
    ("malformed_signature", lambda r, run: r.model_copy(update={"signature": "not-hex!!"})),
]


@pytest.mark.parametrize("name,attack", _RECEIPT_ATTACKS, ids=[n for n, _ in _RECEIPT_ATTACKS])
def test_receipt_attacks_fail(name: str, attack: Callable) -> None:
    run = _run()
    receipt = attack(build_receipt(run, signer=_SIGNER), run)
    assert not verify_receipt(receipt, run=run, signers=_SIGNERS).ok


def test_unknown_key_id_fails() -> None:
    receipt = build_receipt(_run(), signer=_SIGNER)
    assert "unknown-key-id" in verify_receipt(receipt, run=_run(), signers={}).reasons


def test_absent_receipt_fails() -> None:
    assert verify_receipt(None, run=_run(), signers=_SIGNERS).reasons == ("absent-receipt",)


def test_reused_receipt_fails() -> None:
    run = _run()
    receipt = build_receipt(run, signer=_SIGNER)
    seen = {receipt.payload.receipt_id}
    assert (
        "reused-receipt"
        in verify_receipt(receipt, run=run, signers=_SIGNERS, seen_receipt_ids=seen).reasons
    )


def test_wrong_benchmark_problem_and_policy_fail() -> None:
    run = _run()
    receipt = build_receipt(run, signer=_SIGNER)
    assert (
        "benchmark-id"
        in verify_receipt(
            receipt, run=run.model_copy(update={"id": "other"}), signers=_SIGNERS
        ).reasons
    )
    assert (
        "problem"
        in verify_receipt(
            receipt, run=run.model_copy(update={"problem_id": "other"}), signers=_SIGNERS
        ).reasons
    )
    bad_snap = {**(run.policy_snapshot or {}), "policy_id": "lenient-v1"}
    assert (
        "policy-anchor"
        in verify_receipt(
            receipt, run=run.model_copy(update={"policy_snapshot": bad_snap}), signers=_SIGNERS
        ).reasons
    )


def test_metadata_only_coherent_rewrite_fails_receipt() -> None:
    run = _run()
    receipt = build_receipt(run, signer=_SIGNER)
    # Coherently rewrite the exact result's schedule (the worker-output digest changes), keeping
    # the run otherwise internally consistent. The receipt was signed over the original.
    ex = next(r for r in run.solver_results if r.solver_kind == SolverKind.EXACT)
    assert ex.schedule is not None
    forged = ex.model_copy(
        update={"schedule": ex.schedule.model_copy(update={"selected_opportunity_ids": ("OPP-1",)})}
    )
    tampered = run.model_copy(update={"solver_results": [forged, run.solver_results[1]]})
    v = verify_receipt(receipt, run=tampered, signers=_SIGNERS)
    assert not v.ok and "worker-output-digest" in v.reasons


def test_fabricated_artifacts_fail_receipt() -> None:
    run = _run().model_copy(update={"artifacts": [{"type": "t", "checksum": "real"}]})
    receipt = build_receipt(run, signer=_SIGNER)
    fabricated = run.model_copy(update={"artifacts": [{"type": "t", "checksum": "FORGED"}]})
    v = verify_receipt(receipt, run=fabricated, signers=_SIGNERS)
    assert not v.ok and "artifact-manifest-digest" in v.reasons


# ---- full service path ---------------------------------------------------------------------
def test_service_with_signer_accepts_and_persists_receipt(container: AppContainer) -> None:
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, findings = container.optimization_service.benchmark(problem.id, seed=7, run_quantum=False)
    receipt_finding = next(f for f in findings if f.check_id == "opt.execution_receipt")
    assert receipt_finding.passed
    session = container.database.session()
    from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository

    repo = SqlAlchemyOptimizationRepository(session)
    row = repo.get_receipt(run.id)
    accepted = repo.get_benchmark(run.id)
    session.close()
    assert row is not None and row.benchmark_id == run.id and row.signer_key_id
    assert accepted is not None and accepted.verification_passed is True


def test_service_without_signer_leaves_evidence_unaccepted(container: AppContainer) -> None:
    # A service with NO signer: provenance unavailable -> benchmark unaccepted, no memory edges.
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    no_signer = OptimizationService(
        settings=container.settings, database=container.database, receipt_signer=None
    )
    run, findings = no_signer.benchmark(problem.id, seed=7, run_quantum=False)
    receipt_finding = next(f for f in findings if f.check_id == "opt.execution_receipt")
    assert not receipt_finding.passed and "provenance unavailable" in receipt_finding.explanation
    assert run.comparison is not None
    assert run.comparison.conclusion.value == "insufficient-evidence"
    session = container.database.session()
    from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository

    repo = SqlAlchemyOptimizationRepository(session)
    accepted = repo.get_benchmark(run.id)
    receipt = repo.get_receipt(run.id)
    session.close()
    assert accepted is not None and accepted.verification_passed is False
    assert receipt is None
    neighbors = container.memory_service.graph_neighbors(problem.id, depth=1, limit=50)
    assert neighbors.neighbors == []
