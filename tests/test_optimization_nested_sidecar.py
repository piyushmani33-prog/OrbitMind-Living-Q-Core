"""Nested sidecar evidence authentication (final nested-sidecar acceptance).

The remaining High finding: nested ``quantum_evidence`` and ``verification_summary`` could be
removed, emptied, contradicted, or extended while offline AND online authentication still
succeeded. The fix:

* ``quantum_evidence`` (Option A — authoritative): a strict ``QuantumEvidenceSidecarV1`` parse +
  required presence for quantum artifact types + binding to the signed full-evidence digest. Every
  mutation now fails offline and online.
* ``verification_summary`` (Option B — non-authoritative): the build-time finding counts are no
  longer embedded in the authenticated sidecar; ``ArtifactSidecarV1`` (extra="forbid") rejects any
  sidecar that still carries the field, so a forged/contradictory summary fails closed.

The quantum cases need a completed AerSimulator run, so the whole module is skipped when
qiskit/qiskit-aer is unavailable. A single quantum benchmark is built once (module scope) and each
test mutates a COPY of its sidecar; online tests write the mutation to disk and restore afterwards.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from orbitmind.optimization.receipts import (
    authenticate_sidecar_offline,
)
from orbitmind.quantum.adapter import quantum_available

pytestmark = pytest.mark.skipif(not quantum_available(), reason="qiskit/qiskit-aer not installed")

_SIGNING_KEY = "test-evidence-signing-key-0123456789abcdef"


@dataclass
class QFix:
    container: AppContainer
    run_id: str
    problem_id: str
    sidecar: Path
    base: dict  # the pristine on-disk quantum sidecar meta
    root: Path
    artifacts: list[dict]

    @property
    def svc(self):
        return self.container.optimization_service

    @property
    def signers(self):
        return self.svc._receipt_signers

    def meta(self) -> dict:
        """A fresh deep copy of the pristine sidecar meta to mutate."""
        return json.loads(json.dumps(self.base))

    def restore(self) -> None:
        self.sidecar.write_text(json.dumps(self.base), encoding="utf-8")


def _build_quantum(tmp: Path, db_name: str, *, seed: int = 7) -> tuple[AppContainer, object]:
    settings = Settings(
        database_url=f"sqlite:///{(tmp / db_name).as_posix()}",
        artifacts_dir=tmp / "artifacts",
        env="test",
        evidence_signing_key=_SIGNING_KEY,
    )
    container = AppContainer(settings=settings)
    container.init_storage()
    problem = container.optimization_service.create_problem(fixtures.fixture("default"))
    run, _ = container.optimization_service.benchmark(
        problem.id,
        seed=seed,
        shots=128,
        optimizer_iterations=6,
        run_quantum=True,
        generate_artifacts=True,
    )
    return container, run


@pytest.fixture(scope="module")
def qfix(tmp_path_factory: pytest.TempPathFactory) -> Iterator[QFix]:
    tmp = tmp_path_factory.mktemp("nested_sidecar")
    container, run = _build_quantum(tmp, "q.db")
    if run.quantum_experiment is None or run.quantum_experiment.status.value != "completed":
        pytest.skip("quantum experiment did not complete")
    assert container.optimization_service.read_benchmark_evidence(run.id).authenticated
    root = container.settings.resolved_artifacts_dir()
    qside = next(a for a in run.artifacts if a["type"] == "quantum_sample_distribution")
    sidecar = root / (qside["path"] + ".json")
    base = json.loads(sidecar.read_text("utf-8"))
    assert "quantum_evidence" in base and isinstance(base["quantum_evidence"], dict)
    # Option B: the authenticated sidecar no longer carries a verification_summary field.
    assert "verification_summary" not in base
    yield QFix(container, run.id, run.problem_id, sidecar, base, root, list(run.artifacts))


# --------------------------------------------------------------------------------------------------
# quantum_evidence — required-field / wrong-type / shape mutations (OFFLINE)
# --------------------------------------------------------------------------------------------------
_QE_REQUIRED_FIELDS = [
    "problem_checksum",
    "qubo_checksum",
    "variable_mapping",
    "qubit_to_variable",
    "bit_order",
    "encoded_constraints",
    "unencoded_constraints",
    "penalty_value",
    "penalty_source",
    "penalty_sufficient",
    "penalty_satisfying_assignment_exists",
    "penalty_proof_status",
    "penalty_proof_method",
    "manifest_checksum",
    "post_verification_required",
    "simulator_backend",
    "shots",
    "optimizer_iterations",
    "qaoa_layers",
    "transpile_level",
    "seeds",
    "software_versions",
    "limitations",
]


def _off(qfix: QFix, meta: dict) -> tuple[bool, str]:
    return authenticate_sidecar_offline(meta, qfix.signers)


def test_valid_quantum_sidecar_authenticates(qfix: QFix) -> None:
    ok, reason = _off(qfix, qfix.meta())
    assert ok, reason
    assert qfix.svc.read_benchmark_evidence(qfix.run_id).authenticated


@pytest.mark.parametrize(
    "mutate,expect",
    [
        (lambda m: m.pop("quantum_evidence"), "missing-quantum-evidence"),
        (lambda m: m.__setitem__("quantum_evidence", None), "missing-quantum-evidence"),
        (lambda m: m.__setitem__("quantum_evidence", {}), "malformed-quantum-evidence"),
        (lambda m: m.__setitem__("quantum_evidence", []), "unknown-sidecar-field"),
        (lambda m: m.__setitem__("quantum_evidence", "x"), "unknown-sidecar-field"),
        (lambda m: m["quantum_evidence"].__setitem__("forged", 1), "malformed-quantum-evidence"),
    ],
)
def test_quantum_evidence_shape_mutation_fails_offline(qfix: QFix, mutate, expect: str) -> None:
    meta = qfix.meta()
    mutate(meta)
    ok, reason = _off(qfix, meta)
    assert not ok and reason == expect, reason


@pytest.mark.parametrize("field", _QE_REQUIRED_FIELDS)
def test_quantum_evidence_missing_required_field_fails_offline(qfix: QFix, field: str) -> None:
    meta = qfix.meta()
    meta["quantum_evidence"].pop(field)
    ok, reason = _off(qfix, meta)
    assert not ok and reason == "malformed-quantum-evidence", reason


@pytest.mark.parametrize(
    "field,value",
    [
        ("shots", True),  # Boolean cannot satisfy an integer field
        ("shots", "128"),  # numeric string cannot satisfy an integer field
        ("optimizer_iterations", True),
        ("qaoa_layers", "1"),
        ("transpile_level", True),
        ("post_verification_required", 1),  # int cannot satisfy a strict bool
        ("penalty_sufficient", 1),
    ],
)
def test_quantum_evidence_wrong_scalar_type_fails_offline(qfix: QFix, field: str, value) -> None:
    meta = qfix.meta()
    meta["quantum_evidence"][field] = value
    ok, reason = _off(qfix, meta)
    assert not ok and reason == "malformed-quantum-evidence", reason


@pytest.mark.parametrize(
    "field,value",
    [
        ("shots", 999999),
        ("optimizer_iterations", 999),
        ("qaoa_layers", 7),
        ("transpile_level", 3),
        ("seeds", {"forged": 1}),
        ("software_versions", {"qiskit": "0.0.0"}),
        ("limitations", "no limitations"),
        ("bit_order", "big-endian-FORGED"),
        ("qubo_checksum", "0" * 64),
        ("penalty_value", 1234.5),
        ("penalty_proof_status", "unproven-FORGED"),
        ("encoded_constraints", ["FORGED"]),
    ],
)
def test_quantum_evidence_changed_value_fails_offline(qfix: QFix, field: str, value) -> None:
    """A well-shaped but CONTRADICTORY field breaks the signed full-evidence digest."""
    meta = qfix.meta()
    meta["quantum_evidence"][field] = value
    ok, reason = _off(qfix, meta)
    assert not ok and reason in {"quantum-evidence-digest", "evidence-binding"}, reason


def test_quantum_evidence_manifest_checksum_change_fails_offline(qfix: QFix) -> None:
    meta = qfix.meta()
    meta["quantum_evidence"]["manifest_checksum"] = "0" * 64
    ok, reason = _off(qfix, meta)
    assert not ok and reason in {"quantum-evidence-digest", "evidence-binding"}, reason


# --------------------------------------------------------------------------------------------------
# quantum_evidence — ONLINE (read-time) authentication
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.pop("quantum_evidence"),
        lambda m: m.__setitem__("quantum_evidence", None),
        lambda m: m.__setitem__("quantum_evidence", {}),
        lambda m: m["quantum_evidence"].__setitem__("forged", 1),
        lambda m: m["quantum_evidence"].__setitem__("shots", 999999),
        lambda m: m["quantum_evidence"].__setitem__("seeds", {"x": 9}),
        lambda m: m["quantum_evidence"].__setitem__("limitations", "none"),
    ],
)
def test_quantum_evidence_mutation_fails_online(qfix: QFix, mutate) -> None:
    meta = qfix.meta()
    mutate(meta)
    qfix.sidecar.write_text(json.dumps(meta), encoding="utf-8")
    try:
        auth = qfix.svc.read_benchmark_evidence(qfix.run_id)
        assert auth.integrity_failed and not auth.authenticated
        assert auth.safe_conclusion() == "insufficient-evidence"
    finally:
        qfix.restore()


# --------------------------------------------------------------------------------------------------
# verification_summary — Option B: any present summary is an unknown (unsigned) field
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        [],
        "x",
        {"checks": True},
        {"checks": "123"},
        {"checks": 1, "failed": 0, "passed": True},  # forged "all passed"
        {"checks": 1, "failed": 99, "passed": False},  # contradictory
    ],
)
def test_verification_summary_present_fails_offline(qfix: QFix, value) -> None:
    meta = qfix.meta()
    meta["verification_summary"] = value
    ok, reason = _off(qfix, meta)
    assert not ok and reason == "unknown-sidecar-field", reason


def test_verification_summary_present_fails_online(qfix: QFix) -> None:
    meta = qfix.meta()
    meta["verification_summary"] = {"checks": 1, "failed": 0, "passed": True}
    qfix.sidecar.write_text(json.dumps(meta), encoding="utf-8")
    try:
        auth = qfix.svc.read_benchmark_evidence(qfix.run_id)
        assert auth.integrity_failed and not auth.authenticated
    finally:
        qfix.restore()


# --------------------------------------------------------------------------------------------------
# Full service / API acceptance behaviour for representative nested mutations
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.__setitem__("quantum_evidence", None),
        lambda m: m["quantum_evidence"].__setitem__("forged", "x"),
        lambda m: m.__setitem__("verification_summary", {"checks": 1, "failed": 0, "passed": True}),
    ],
)
def test_nested_mutation_api_behavior(qfix: QFix, mutate) -> None:
    meta = qfix.meta()
    mutate(meta)
    qfix.sidecar.write_text(json.dumps(meta), encoding="utf-8")
    try:
        with TestClient(create_app(qfix.container)) as client:
            bench = client.get(f"/api/v1/optimization/benchmarks/{qfix.run_id}")
            assert bench.status_code == 200
            body = bench.json()
            assert body["integrity_failed"] and not body["verified"]
            assert body["run"]["conclusion"] == "insufficient-evidence"
            # Artifacts withheld with a bounded error, not an authenticated 200.
            assert (
                client.get(f"/api/v1/optimization/runs/{qfix.run_id}/artifacts").status_code == 422
            )
            # Run list marks it integrity-failed.
            listing = client.get("/api/v1/optimization/runs").json()
            item = next(i for i in listing["items"] if i["id"] == qfix.run_id)
            assert item["integrity_failed"] and not item["verified"]
            # Benchmark-scoped evidence graph + generic memory navigation: edges invalid.
            graph = client.get(
                f"/api/v1/optimization/benchmarks/{qfix.run_id}/evidence-graph"
            ).json()
            assert graph["integrity_failed"] and not graph["valid_evidence"]
            generic = client.get(f"/api/v1/memory/graph/{qfix.problem_id}/neighbors").json()
            edges = [n for n in generic["neighbors"] if n["benchmark_id"] == qfix.run_id]
            assert edges and all(n["evidence_validity"] == "integrity-failed" for n in edges)
    finally:
        qfix.restore()


def test_nested_mutation_writes_integrity_audit(qfix: QFix) -> None:
    from sqlalchemy import text

    meta = qfix.meta()
    meta.pop("quantum_evidence")
    qfix.sidecar.write_text(json.dumps(meta), encoding="utf-8")
    try:
        qfix.svc.read_benchmark_evidence(qfix.run_id)
        with qfix.container.database.engine.connect() as conn:
            n = conn.execute(
                text(
                    "SELECT count(*) FROM audit_events "
                    "WHERE action='optimization.benchmark_integrity_failed'"
                )
            ).scalar_one()
        assert n >= 1
    finally:
        qfix.restore()


def test_quantum_evidence_block_copied_from_another_benchmark_fails(
    qfix: QFix, tmp_path: Path
) -> None:
    """A perfectly-shaped evidence block from a DIFFERENT benchmark breaks the signed digest."""
    # A different seed yields genuinely different evidence (seeds/parameters differ).
    other_container, other_run = _build_quantum(tmp_path, "other.db", seed=11)
    if (
        other_run.quantum_experiment is None
        or other_run.quantum_experiment.status.value != "completed"
    ):
        pytest.skip("second quantum experiment did not complete")
    other_root = other_container.settings.resolved_artifacts_dir()
    other_side = next(a for a in other_run.artifacts if a["type"] == "quantum_sample_distribution")
    other_meta = json.loads((other_root / (other_side["path"] + ".json")).read_text("utf-8"))
    meta = qfix.meta()
    meta["quantum_evidence"] = other_meta["quantum_evidence"]  # foreign-but-valid block
    ok, reason = _off(qfix, meta)
    assert not ok and reason in {"quantum-evidence-digest", "evidence-binding"}, reason


# --------------------------------------------------------------------------------------------------
# A non-quantum (classical) artifact must NOT carry a quantum-evidence block.
# --------------------------------------------------------------------------------------------------
def test_classical_sidecar_rejects_quantum_evidence(qfix: QFix) -> None:
    """Inject a quantum-evidence block into a CLASSICAL artifact sidecar; it must be rejected."""
    classical_art = next(
        a
        for a in qfix.artifacts
        if a["type"] not in ("quantum_sample_distribution", "quantum_circuit_diagram")
    )
    classical = qfix.root / (classical_art["path"] + ".json")
    assert classical.is_file()
    cmeta = json.loads(classical.read_text("utf-8"))
    assert "quantum_evidence" not in cmeta
    # A classical sidecar authenticates as-is; injecting a foreign evidence block must be rejected.
    ok0, _ = authenticate_sidecar_offline(cmeta, qfix.signers)
    assert ok0
    cmeta["quantum_evidence"] = qfix.base["quantum_evidence"]  # inject onto a classical artifact
    ok, reason = authenticate_sidecar_offline(cmeta, qfix.signers)
    assert not ok and reason == "unexpected-quantum-evidence", reason
