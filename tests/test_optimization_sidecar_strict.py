"""Strict receipt-bound sidecar authentication (final sidecar acceptance, High 1 + High 2).

High 1: a sidecar with NO receipt envelope must fail online (not only offline).
High 2: unknown top-level sidecar fields must fail parsing (no unsigned metadata).
"""

from __future__ import annotations

import json

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization.receipts import (
    RECEIPT_ENVELOPE_KEY,
    authenticate_sidecar_offline,
)


def _accepted_with_artifacts(container: AppContainer):
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run, _ = svc.benchmark(problem.id, seed=7, run_quantum=False, generate_artifacts=True)
    assert svc.read_benchmark_evidence(run.id).authenticated
    root = container.settings.resolved_artifacts_dir()
    sidecar = root / (run.artifacts[0]["path"] + ".json")
    return svc, run, sidecar


@pytest.fixture
def client_container(container: AppContainer):
    from fastapi.testclient import TestClient

    from orbitmind.api.app import create_app

    with TestClient(create_app(container)) as client:
        yield client, container


# --- High 1: missing receipt envelope must fail OFFLINE and ONLINE ---
def test_missing_envelope_fails_offline(container: AppContainer) -> None:
    svc, _run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta[RECEIPT_ENVELOPE_KEY]
    ok, reason = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert not ok and reason == "no-receipt-envelope"


def test_missing_envelope_fails_online_read(container: AppContainer) -> None:
    svc, run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta[RECEIPT_ENVELOPE_KEY]
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated
    assert auth.safe_conclusion() == "insufficient-evidence"


def test_missing_envelope_endpoints(client_container) -> None:
    client, container = client_container
    svc, run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta[RECEIPT_ENVELOPE_KEY]
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    # Benchmark read: bounded integrity response (200 with integrity_failed + non-positive
    # conclusion), never a positive authenticated serve.
    bench = client.get(f"/api/v1/optimization/benchmarks/{run.id}")
    assert bench.status_code == 200
    assert bench.json()["integrity_failed"] and not bench.json()["verified"]
    assert bench.json()["run"]["conclusion"] == "insufficient-evidence"
    # Artifacts: withheld with a bounded error (422), not authenticated 200.
    assert client.get(f"/api/v1/optimization/runs/{run.id}/artifacts").status_code == 422
    # Run list marks it integrity-failed.
    listing = client.get("/api/v1/optimization/runs").json()
    item = next(i for i in listing["items"] if i["id"] == run.id)
    assert item["integrity_failed"] and not item["verified"]
    # Benchmark-scoped graph: edges invalid.
    graph = client.get(f"/api/v1/optimization/benchmarks/{run.id}/evidence-graph").json()
    assert graph["integrity_failed"] and not graph["valid_evidence"]
    # Generic memory navigation marks this benchmark's edges invalid.
    generic = client.get(f"/api/v1/memory/graph/{run.problem_id}/neighbors").json()
    edges = [n for n in generic["neighbors"] if n["benchmark_id"] == run.id]
    assert edges and all(n["evidence_validity"] == "integrity-failed" for n in edges)


def test_missing_envelope_writes_integrity_audit(container: AppContainer) -> None:
    from sqlalchemy import text

    svc, run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta[RECEIPT_ENVELOPE_KEY]
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    svc.read_benchmark_evidence(run.id)
    with container.database.engine.connect() as conn:
        n = conn.execute(
            text(
                "SELECT count(*) FROM audit_events "
                "WHERE action='optimization.benchmark_integrity_failed'"
            )
        ).scalar_one()
    assert n >= 1


# --- High 2: unknown / forged top-level fields must fail ---
@pytest.mark.parametrize(
    "field",
    [
        "artifact_id",
        "exact_result_id",
        "greedy_result_id",
        "quantum_experiment_id",
        "evidence_manifest_checksum",
        "arbitrary_unknown_field",
    ],
)
def test_unknown_top_level_field_fails_offline(container: AppContainer, field: str) -> None:
    svc, _run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    meta[field] = "FORGED"  # a field NOT in the declared sidecar schema
    ok, reason = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert not ok, f"forged top-level {field} was accepted"


def test_unknown_top_level_field_fails_online(container: AppContainer) -> None:
    svc, run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    meta["exact_result_id"] = "FORGED"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    auth = svc.read_benchmark_evidence(run.id)
    assert auth.integrity_failed and not auth.authenticated


def test_valid_sidecar_still_authenticates(container: AppContainer) -> None:
    svc, run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    ok, reason = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert ok, reason
    assert svc.read_benchmark_evidence(run.id).authenticated


# --- format-version matrix (step 13): only the literal "1" is valid; bound to the receipt ---
@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.pop("sidecar_format_version"),  # missing
        lambda m: m.__setitem__("sidecar_format_version", "0"),
        lambda m: m.__setitem__("sidecar_format_version", "2"),
        lambda m: m.__setitem__("sidecar_format_version", 1),  # integer, not "1"
        lambda m: m.__setitem__("sidecar_format_version", None),
    ],
)
def test_sidecar_format_version_invalid_fails(container: AppContainer, mutate) -> None:
    svc, _run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    mutate(meta)
    ok, _reason = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert not ok


def test_format_version_changed_in_entry_fails(container: AppContainer) -> None:
    # The format version is receipt-bound through the canonical entry: changing the ENTRY's value
    # breaks the manifest digest (step 7).
    from orbitmind.optimization.receipts import ARTIFACT_ENTRY_KEY

    svc, _run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    meta[ARTIFACT_ENTRY_KEY] = {**meta[ARTIFACT_ENTRY_KEY], "sidecar_format_version": "2"}
    ok, _reason = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert not ok


# --- envelope mutation matrix (step 14) ---
@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda e: e.pop("payload_checksum"), "incomplete-receipt-envelope"),
        (lambda e: e.pop("signature"), "incomplete-receipt-envelope"),
        (lambda e: e.__setitem__("extra", 1), "incomplete-receipt-envelope"),
        (lambda e: e.__setitem__("payload_checksum", "0" * 64), "payload-checksum"),
        (lambda e: e.__setitem__("signature", "0" * 64), "signature"),
        (lambda e: e.__setitem__("receipt_id", "forged"), "envelope-payload-mismatch"),
        (lambda e: e.__setitem__("signer_key_id", "forged"), "envelope-payload-mismatch"),
        (lambda e: e.__setitem__("signature_algorithm", "RSA"), "envelope-payload-mismatch"),
    ],
)
def test_envelope_mutation_matrix(container: AppContainer, mutate, reason: str) -> None:
    svc, _run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    mutate(meta[RECEIPT_ENVELOPE_KEY])
    ok, got = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert not ok and got == reason


def test_envelope_payload_tamper_fails(container: AppContainer) -> None:
    svc, _run, sidecar = _accepted_with_artifacts(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    meta[RECEIPT_ENVELOPE_KEY]["payload"]["benchmark_id"] = "FORGED"
    ok, _reason = authenticate_sidecar_offline(meta, svc._receipt_signers)
    assert not ok


def test_envelope_copied_from_another_benchmark_fails(container: AppContainer) -> None:
    svc = container.optimization_service
    problem = svc.create_problem(fixtures.fixture("default"))
    run_a, _ = svc.benchmark(problem.id, seed=7, run_quantum=False, generate_artifacts=True)
    run_b, _ = svc.benchmark(problem.id, seed=11, run_quantum=False, generate_artifacts=True)
    root = container.settings.resolved_artifacts_dir()
    meta_a = json.loads((root / (run_a.artifacts[0]["path"] + ".json")).read_text("utf-8"))
    meta_b = json.loads((root / (run_b.artifacts[0]["path"] + ".json")).read_text("utf-8"))
    meta_a[RECEIPT_ENVELOPE_KEY] = meta_b[RECEIPT_ENVELOPE_KEY]  # B's envelope into A's sidecar
    ok, _reason = authenticate_sidecar_offline(meta_a, svc._receipt_signers)
    assert not ok
