"""Strict receipt schema + independent config-digest recomputation (fourth review, High #2)."""

from __future__ import annotations

import pytest

from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.models import BenchmarkRun, SolverKind
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.receipts import (
    BenchmarkExecutionReceipt,
    HmacSha256EvidenceReceiptSigner,
    ReceiptPayload,
    _payload_bytes,
    _payload_checksum,
    build_receipt,
    verify_receipt,
)
from orbitmind.quantum.adapter import quantum_available

_PROBLEM = normalize_problem(fixtures.fixture("default"))
_SIGNER = HmacSha256EvidenceReceiptSigner(b"x" * 32, "unit-key")
_SIGNERS = {"unit-key": _SIGNER}


def _run() -> BenchmarkRun:
    return run_benchmark(_PROBLEM, seed=7, run_quantum=False)


def _resign(payload: ReceiptPayload) -> BenchmarkExecutionReceipt:
    """Re-sign a (possibly mutated) payload so the HMAC is valid — isolates the schema check."""
    return BenchmarkExecutionReceipt(
        payload=payload,
        payload_checksum=_payload_checksum(payload),
        signature=_SIGNER.sign(_payload_bytes(payload)),
    )


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("signature_algorithm", "RSA-2048", "signature-algorithm"),
        ("receipt_format_version", "9.9", "format-version"),
        ("comparison_algorithm_version", "99", "comparison-algorithm"),
        ("issued_at", "", "issued-at-empty"),
        ("issued_at", "not-a-timestamp", "issued-at-malformed"),
        ("receipt_id", "short", "receipt-id-format"),
    ],
)
def test_strict_schema_rejects_bad_signed_fields(field: str, value: str, reason: str) -> None:
    run = _run()
    base = build_receipt(run, signer=_SIGNER).payload
    forged = _resign(base.model_copy(update={field: value}))
    result = verify_receipt(forged, run=run, signers=_SIGNERS)
    assert not result.ok and reason in result.reasons


def test_changed_exact_config_invalidates_receipt() -> None:
    run = _run()
    receipt = build_receipt(run, signer=_SIGNER)
    ex = next(r for r in run.solver_results if r.solver_kind == SolverKind.EXACT)
    tampered_cfg = ex.configuration.model_copy(update={"timeout_seconds": 999.0})
    tampered = run.model_copy(
        update={
            "solver_results": [
                ex.model_copy(update={"configuration": tampered_cfg}),
                run.solver_results[1],
            ]
        }
    )
    result = verify_receipt(receipt, run=tampered, signers=_SIGNERS)
    assert not result.ok and "exact-config-digest" in result.reasons


def test_changed_artifact_inventory_invalidates_receipt() -> None:
    run = _run().model_copy(update={"artifacts": [{"type": "t", "checksum": "real"}]})
    receipt = build_receipt(run, signer=_SIGNER)
    fabricated = run.model_copy(update={"artifacts": [{"type": "t", "checksum": "FORGED"}]})
    result = verify_receipt(receipt, run=fabricated, signers=_SIGNERS)
    assert not result.ok and "artifact-manifest-digest" in result.reasons


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
def test_quantum_config_and_circuit_and_nonce_tampers_invalidate_receipt() -> None:
    run = run_benchmark(_PROBLEM, seed=7, shots=128, optimizer_iterations=6, run_quantum=True)
    q = run.quantum_experiment
    if q is None or q.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    receipt = build_receipt(run, signer=_SIGNER)
    assert verify_receipt(receipt, run=run, signers=_SIGNERS).ok
    # Changed quantum configuration (iteration count) -> quantum-config-digest mismatch.
    bad_cfg = run.model_copy(
        update={
            "quantum_experiment": q.model_copy(
                update={
                    "configuration": q.configuration.model_copy(update={"optimizer_iterations": 99})
                }
            )
        }
    )
    assert "quantum-config-digest" in verify_receipt(receipt, run=bad_cfg, signers=_SIGNERS).reasons
    # Changed worker nonce -> worker-nonce-mismatch.
    bad_nonce = run.model_copy(
        update={"quantum_experiment": q.model_copy(update={"execution_nonce": "b" * 32})}
    )
    assert (
        "worker-nonce-mismatch" in verify_receipt(receipt, run=bad_nonce, signers=_SIGNERS).reasons
    )
