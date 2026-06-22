"""Receipt-bound sidecars + detached offline authentication (fourth review, High #1)."""

from __future__ import annotations

import json

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization.receipts import (
    ARTIFACT_ENTRY_KEY,
    ARTIFACT_MANIFEST_KEY,
    RECEIPT_ENVELOPE_KEY,
    authenticate_sidecar_offline,
)
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark


def _summary_sidecar(container: AppContainer):
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    root = container.settings.resolved_artifacts_dir()
    summary = next(a for a in run.artifacts if a["type"] == "benchmark_summary_json")
    sidecar = root / (summary["path"] + ".json")
    return container.optimization_service._receipt_signers, sidecar, run


def test_sidecar_embeds_receipt_and_authenticates_offline(container: AppContainer) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    assert RECEIPT_ENVELOPE_KEY in meta  # receipt linkage embedded
    env = meta[RECEIPT_ENVELOPE_KEY]
    assert env["receipt_id"] and env["signer_key_id"] and env["signature"] and env["payload"]
    assert "secret" not in json.dumps(env).lower()  # no signing secret embedded
    ok, reason = authenticate_sidecar_offline(meta, signers)  # NO database access
    assert ok, reason


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda m: m.pop(RECEIPT_ENVELOPE_KEY), "no-receipt-envelope"),
        (lambda m: m.__setitem__("benchmark_id", "FORGED"), "sidecar-binding"),
        (
            lambda m: m[RECEIPT_ENVELOPE_KEY].__setitem__("signature", "00" * 32),
            "signature",
        ),
    ],
)
def test_offline_authentication_rejects_tampering(
    container: AppContainer, mutate, expected: str
) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    mutate(meta)
    ok, reason = authenticate_sidecar_offline(meta, signers)
    assert not ok and reason == expected


def test_offline_authentication_unknown_key_fails(container: AppContainer) -> None:
    _signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    ok, reason = authenticate_sidecar_offline(meta, {})  # no keys configured
    assert not ok and reason == "unknown-key-id"


def test_substituted_receipt_from_another_benchmark_fails(container: AppContainer) -> None:
    signers, sidecar_a, _run = _summary_sidecar(container)
    _signers2, sidecar_b, _run2 = _summary_sidecar(container)  # a different benchmark
    meta_a = json.loads(sidecar_a.read_text("utf-8"))
    meta_b = json.loads(sidecar_b.read_text("utf-8"))
    # Splice benchmark B's receipt envelope into benchmark A's sidecar.
    meta_a[RECEIPT_ENVELOPE_KEY] = meta_b[RECEIPT_ENVELOPE_KEY]
    ok, reason = authenticate_sidecar_offline(meta_a, signers)
    assert not ok and reason == "sidecar-binding"


def test_online_verifier_requires_present_sidecar_fields(container: AppContainer) -> None:
    # A sidecar MISSING a material field must fail (no get-default-to-trusted; High #1 #8).
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id, seed=7, run_quantum=False, generate_artifacts=True
    )
    stored = container.optimization_service.get_problem(problem.id)
    assert stored is not None
    root = container.settings.resolved_artifacts_dir()
    sidecar = root / (run.artifacts[0]["path"] + ".json")
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta["benchmark_id"]  # remove a required field
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    findings = verify_benchmark(stored, run, artifacts_root=root)
    assert not all_critical_passed(findings)


# --- fifth review, High #1: offline authentication proves artifact-manifest membership ---
def test_offline_auth_proves_manifest_membership(container: AppContainer) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    assert ARTIFACT_ENTRY_KEY in meta and ARTIFACT_MANIFEST_KEY in meta
    # The embedded entry is a member of the manifest, and supplying the artifact checksum passes.
    checksum = meta[ARTIFACT_ENTRY_KEY]["artifact_checksum"]
    ok, reason = authenticate_sidecar_offline(meta, signers, artifact_checksum=checksum)
    assert ok, reason


def test_offline_auth_rejects_forged_manifest_entry(container: AppContainer) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    # A valid receipt but an entry NOT in the signed manifest must fail.
    meta[ARTIFACT_ENTRY_KEY] = {**meta[ARTIFACT_ENTRY_KEY], "artifact_checksum": "FORGED"}
    ok, reason = authenticate_sidecar_offline(meta, signers)
    assert not ok and reason == "entry-not-in-manifest"


def test_offline_auth_rejects_forged_manifest_digest(container: AppContainer) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    # Replace the manifest with a fabricated one (still containing the entry) -> digest mismatch.
    forged = dict(meta[ARTIFACT_ENTRY_KEY])
    meta[ARTIFACT_MANIFEST_KEY] = [meta[ARTIFACT_ENTRY_KEY], {**forged, "artifact_checksum": "x"}]
    ok, reason = authenticate_sidecar_offline(meta, signers)
    assert not ok and reason == "artifact-manifest-digest"


def test_offline_auth_rejects_missing_manifest(container: AppContainer) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta[ARTIFACT_MANIFEST_KEY]
    ok, reason = authenticate_sidecar_offline(meta, signers)
    assert not ok and reason == "no-artifact-manifest"


def test_offline_auth_rejects_incomplete_receipt_envelope(container: AppContainer) -> None:
    signers, sidecar, _run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    del meta[RECEIPT_ENVELOPE_KEY]["receipt_id"]  # missing required envelope field
    ok, reason = authenticate_sidecar_offline(meta, signers)
    assert not ok and reason == "incomplete-receipt-envelope"


def test_offline_auth_rejects_sidecar_copied_to_another_artifact(container: AppContainer) -> None:
    # Splice artifact B's entry into A's sidecar: B's entry is a valid member, but the supplied
    # artifact file checksum (A's) no longer matches -> rejected.
    signers, sidecar, run = _summary_sidecar(container)
    meta = json.loads(sidecar.read_text("utf-8"))
    a_checksum = meta[ARTIFACT_ENTRY_KEY]["artifact_checksum"]
    other = next(e for e in meta[ARTIFACT_MANIFEST_KEY] if e["artifact_checksum"] != a_checksum)
    meta[ARTIFACT_ENTRY_KEY] = other  # a different (but valid-member) artifact's entry
    ok, reason = authenticate_sidecar_offline(meta, signers, artifact_checksum=a_checksum)
    assert not ok and reason == "artifact-checksum"
