"""Artifact + sidecar containment, semantics, and self-describing evidence (High finding #5)."""

from __future__ import annotations

import json

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.optimization import fixtures
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark
from orbitmind.quantum.adapter import quantum_available


def _benchmark_with_artifacts(container: AppContainer, *, run_quantum: bool):
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id,
        seed=7,
        shots=128,
        optimizer_iterations=6,
        run_quantum=run_quantum,
        generate_artifacts=True,
    )
    stored = container.optimization_service.get_problem(problem.id)
    assert stored is not None
    root = container.settings.resolved_artifacts_dir()
    return stored, run, root


def test_generated_artifacts_verify(container: AppContainer) -> None:
    problem, run, root = _benchmark_with_artifacts(container, run_quantum=False)
    findings = verify_benchmark(problem, run, artifacts_root=root)
    assert all_critical_passed(findings)
    assert len(run.artifacts) >= 4


def test_external_sidecar_path_is_rejected(container: AppContainer) -> None:
    problem, run, root = _benchmark_with_artifacts(container, run_quantum=False)
    art = dict(run.artifacts[0])
    art["sidecar_path"] = "../outside-sidecar.json"  # not the derived name
    tampered = run.model_copy(update={"artifacts": [art, *run.artifacts[1:]]})
    findings = verify_benchmark(problem, tampered, artifacts_root=root)
    assert not all_critical_passed(findings)


def test_path_traversal_artifact_is_rejected(container: AppContainer) -> None:
    problem, run, root = _benchmark_with_artifacts(container, run_quantum=False)
    art = dict(run.artifacts[0])
    art["path"] = "../escape.png"
    tampered = run.model_copy(update={"artifacts": [art, *run.artifacts[1:]]})
    findings = verify_benchmark(problem, tampered, artifacts_root=root)
    assert not all_critical_passed(findings)


def test_sidecar_overclaim_language_is_rejected(container: AppContainer) -> None:
    problem, run, root = _benchmark_with_artifacts(container, run_quantum=False)
    # Overwrite a real sidecar with misleading quantum-advantage language but a valid checksum.
    art = run.artifacts[0]
    sidecar = root / (art["path"] + ".json")
    meta = json.loads(sidecar.read_text("utf-8"))
    meta["limitations"] = "quantum advantage verified; faster than classical"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    findings = {f.check_id: f for f in verify_benchmark(problem, run, artifacts_root=root)}
    overclaim = [k for k in findings if k.startswith("opt.artifact_no_overclaim")]
    assert overclaim and not findings[overclaim[0]].passed


def test_sidecar_wrong_type_is_rejected(container: AppContainer) -> None:
    problem, run, root = _benchmark_with_artifacts(container, run_quantum=False)
    art = run.artifacts[0]
    sidecar = root / (art["path"] + ".json")
    meta = json.loads(sidecar.read_text("utf-8"))
    meta["artifact_type"] = "totally-different-type"
    sidecar.write_text(json.dumps(meta), encoding="utf-8")
    findings = verify_benchmark(problem, run, artifacts_root=root)
    assert not all_critical_passed(findings)


def test_summary_is_self_describing_without_quantum(container: AppContainer) -> None:
    _problem, run, root = _benchmark_with_artifacts(container, run_quantum=False)
    summary = next(a for a in run.artifacts if a["type"] == "benchmark_summary_json")
    data = json.loads((root / summary["path"]).read_text("utf-8"))
    assert "quantum_evidence" in data and data["quantum_evidence"] is None  # no quantum run
    assert data["problem"]["checksum"]


@pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")
def test_quantum_sidecar_and_summary_carry_evidence(container: AppContainer) -> None:
    _problem, run, root = _benchmark_with_artifacts(container, run_quantum=True)
    if run.quantum_experiment is None or run.quantum_experiment.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    summary = next(a for a in run.artifacts if a["type"] == "benchmark_summary_json")
    data = json.loads((root / summary["path"]).read_text("utf-8"))
    ev = data["quantum_evidence"]
    assert ev is not None
    for key in ("qubo_checksum", "manifest_checksum", "bit_order", "penalty_proof_status"):
        assert ev.get(key), f"summary evidence missing {key}"
    # A quantum-relevant sidecar carries the same self-describing evidence block.
    qsidecars = [
        a
        for a in run.artifacts
        if a["type"] in ("quantum_sample_distribution", "quantum_circuit_diagram")
    ]
    assert qsidecars
    side = json.loads((root / (qsidecars[0]["path"] + ".json")).read_text("utf-8"))
    assert side["quantum_evidence"]["manifest_checksum"] == ev["manifest_checksum"]
