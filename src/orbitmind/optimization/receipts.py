"""Signed benchmark execution receipts (third Codex review, High #1).

The semantic verifier proves a benchmark is mathematically self-consistent; it cannot prove
the recorded samples came from an OrbitMind-controlled execution. A receipt closes that gap:
the trusted parent runtime derives canonical digests over the benchmark's evidence and signs
them with a configured secret (HMAC-SHA256, standard library only). Verifying the receipt
proves the receipt was issued by a trusted runtime holding the secret AND that the persisted
run still matches what was signed.

TRUST BOUNDARY. Trusted: the running OrbitMind process, its isolated quantum worker, this
signing component, the signing key (supplied OUTSIDE the database), and the reviewed code +
policy registry. NOT trusted as evidence by itself: persisted rows, API data, artifact JSON,
sidecars, mutable storage, imported records. NOT protected against: an attacker controlling
the runtime, possessing the key, or replacing both code and signing infrastructure. An HMAC
receipt does NOT prove Qiskit/Aer is scientifically correct — only that a trusted runtime
issued the receipt.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import timedelta
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.optimization.models import (
    BenchmarkRun,
    ExperimentStatus,
    QuantumExperiment,
    SolverKind,
)

RECEIPT_FORMAT_VERSION = "1.0"
COMPARISON_ALGORITHM_VERSION = "1.0"
SUPPORTED_RECEIPT_FORMAT_VERSIONS = frozenset({"1.0"})
SUPPORTED_SIGNATURE_ALGORITHMS = frozenset({"HMAC-SHA256"})
SUPPORTED_COMPARISON_ALGORITHM_VERSIONS = frozenset({"1.0"})
# Worker nonce: secrets.token_hex(16) => 16 bytes / 128 bits of entropy => 32 hex chars.
MIN_NONCE_HEX_LEN = 32
_SHA256_HEX_LEN = 64
# issued_at acceptance window: a small forward clock-skew tolerance; a generous backward bound
# (receipts are persisted long-lived) that still rejects nonsensical pre-2000 / far-future dates.
_ISSUED_AT_FUTURE_SKEW = timedelta(minutes=5)
_ISSUED_AT_MAX_AGE = timedelta(days=3650)


def _is_valid_worker_nonce(nonce: object) -> bool:
    """A worker nonce must be a lowercase-hex string of >= MIN_NONCE_HEX_LEN chars (128-bit)."""
    if not isinstance(nonce, str) or len(nonce) < MIN_NONCE_HEX_LEN:
        return False
    try:
        bytes.fromhex(nonce)
    except ValueError:
        return False
    return nonce == nonce.lower()


def quantum_execution_receipt_eligible(experiment: QuantumExperiment | None) -> bool:
    """A quantum execution receipt may be created ONLY for a genuinely completed worker run
    (fourth review, Critical #1): status is exactly COMPLETED, the worker returned its own
    valid cryptographic nonce, circuit metadata exists, and samples were produced. The trusted
    parent NEVER invents a missing nonce."""
    return (
        experiment is not None
        and experiment.status == ExperimentStatus.COMPLETED
        and _is_valid_worker_nonce(experiment.execution_nonce)
        and experiment.circuit_metadata is not None
        and bool(experiment.samples)
    )


@runtime_checkable
class EvidenceReceiptSigner(Protocol):
    """Signs a canonical payload. The secret never leaves the signer instance."""

    key_id: str
    algorithm: str

    def sign(self, payload: bytes) -> str: ...


class HmacSha256EvidenceReceiptSigner:
    """HMAC-SHA256 signer. The secret is held in memory only — never persisted/logged/returned."""

    algorithm = "HMAC-SHA256"

    def __init__(self, secret: bytes, key_id: str) -> None:
        if not secret:
            raise ValueError("evidence signing secret must be non-empty")
        self._secret = secret
        self.key_id = key_id

    def sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()


class ReceiptPayload(BaseModel):
    """The canonical, signed receipt payload. Frozen; serialized deterministically. Unknown
    fields are rejected so a persisted payload with extra keys fails closed (fifth review,
    Medium #1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_format_version: str
    receipt_id: str
    benchmark_id: str
    problem_id: str | None
    problem_checksum: str
    policy_id: str
    policy_version: str
    policy_checksum: str
    comparison_algorithm_version: str
    exact_result_id: str | None
    greedy_result_id: str | None
    quantum_experiment_id: str | None
    exact_config_checksum: str
    greedy_config_checksum: str
    quantum_config_checksum: str | None
    evidence_manifest_checksum: str | None
    sample_map_digest: str | None
    selected_parameter_digest: str | None
    circuit_metadata_digest: str | None
    software_version_digest: str | None
    artifact_manifest_digest: str | None
    scientific_metadata_digest: str
    best_feasible_sample_digest: str | None
    best_infeasible_sample_digest: str | None
    selected_schedule_digest: str | None
    selected_evaluation_digest: str | None
    # None for a benchmark with no completed quantum worker (the parent NEVER fabricates one).
    worker_execution_nonce: str | None
    worker_output_digest: str
    issued_at: str
    signer_key_id: str
    signature_algorithm: str


class BenchmarkExecutionReceipt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    payload: ReceiptPayload
    payload_checksum: str
    signature: str


class EvidenceReceiptVerification(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    reasons: tuple[str, ...] = ()


def _payload_bytes(payload: ReceiptPayload) -> bytes:
    import json

    return json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_HEX_LEN
        and value == value.lower()
        and all(c in "0123456789abcdef" for c in value)
    )


def _strict_schema_reasons(receipt: BenchmarkExecutionReceipt) -> list[str]:
    """Validate the SEMANTICS of the signed fields, failing closed on unknown/malformed values."""
    import uuid
    from datetime import datetime

    from orbitmind.core.timeutils import utcnow

    p = receipt.payload
    reasons: list[str] = []
    if p.receipt_format_version not in SUPPORTED_RECEIPT_FORMAT_VERSIONS:
        reasons.append("format-version")
    if p.signature_algorithm not in SUPPORTED_SIGNATURE_ALGORITHMS:
        reasons.append("signature-algorithm")
    if p.comparison_algorithm_version not in SUPPORTED_COMPARISON_ALGORITHM_VERSIONS:
        reasons.append("comparison-algorithm")
    # The receipt id must be a real UUID (fifth review, Medium #1).
    try:
        uuid.UUID(str(p.receipt_id))
    except (ValueError, AttributeError, TypeError):
        reasons.append("receipt-id-format")
    if not _is_sha256_hex(receipt.signature):
        reasons.append("signature-encoding")
    if not _is_sha256_hex(receipt.payload_checksum):
        reasons.append("payload-checksum-encoding")
    # issued_at must be a non-empty, timezone-aware UTC timestamp inside a bounded acceptance
    # window (reject naive/non-UTC/empty/far-future timestamps; fifth review, Medium #1).
    if not isinstance(p.issued_at, str) or not p.issued_at:
        reasons.append("issued-at-empty")
    else:
        try:
            ts = datetime.fromisoformat(p.issued_at)
            now = utcnow()
            if ts.tzinfo is None:
                reasons.append("issued-at-naive")
            elif ts.utcoffset() != timedelta(0):
                reasons.append("issued-at-not-utc")
            elif ts > now + _ISSUED_AT_FUTURE_SKEW:
                reasons.append("issued-at-future")
            elif ts < now - _ISSUED_AT_MAX_AGE:
                reasons.append("issued-at-too-old")
        except ValueError:
            reasons.append("issued-at-malformed")
    if not p.signer_key_id:
        reasons.append("signer-key-id-empty")
    # Required complete digest set (each must be a present string of the right shape).
    for digest in (
        p.exact_config_checksum,
        p.greedy_config_checksum,
        p.worker_output_digest,
    ):
        if not _is_sha256_hex(digest):
            reasons.append("digest-shape")
            break
    return reasons


def _payload_checksum(payload: ReceiptPayload) -> str:
    return hashlib.sha256(_payload_bytes(payload)).hexdigest()


# ---- canonical digests derived from the run (shared by build + verify) ---------------------
def _config_checksum(result_config: dict[str, Any] | None) -> str | None:
    return sha256_canonical_json(result_config) if result_config is not None else None


def _canonical_full_sample(s: Any | None) -> list[Any] | None:
    """The COMPLETE canonical record for a single sample (final acceptance, High 1)."""
    if s is None:
        return None
    return [
        s.bitstring,
        s.count,
        s.probability,
        s.feasible,
        s.raw_mission_value,
        s.objective_value,
        s.qubo_energy,
        s.violations_count,
    ]


def sample_map_digest(run: BenchmarkRun) -> str | None:
    """Digest over the COMPLETE ordered collection of canonical sample records (final acceptance,
    Critical 1): every persisted sample field is bound, so a coordinated parent+child mutation of
    a finite raw mission value or violation count invalidates the receipt."""
    q = run.quantum_experiment
    if q is None or not q.samples:
        return None
    rows = sorted(_canonical_full_sample(s) or [] for s in q.samples)
    return sha256_canonical_json(rows)


def best_feasible_sample_digest(run: BenchmarkRun) -> str | None:
    """Bind the COMPLETE denormalized best-feasible sample (final acceptance, High 1)."""
    q = run.quantum_experiment
    if q is None:
        return None
    return sha256_canonical_json(_canonical_full_sample(q.best_feasible_sample))


def best_infeasible_sample_digest(run: BenchmarkRun) -> str | None:
    """Bind the COMPLETE denormalized best-infeasible sample (final acceptance, High 1)."""
    q = run.quantum_experiment
    if q is None:
        return None
    return sha256_canonical_json(_canonical_full_sample(q.best_infeasible_sample))


def selected_schedule_digest(run: BenchmarkRun) -> str | None:
    """Bind the canonical selected schedule (problem checksum + ordered selected ids + producer)."""
    q = run.quantum_experiment
    if q is None or q.selected_schedule is None:
        return None
    sched = q.selected_schedule
    return sha256_canonical_json(
        {
            "problem_checksum": sched.problem_checksum,
            "selected_opportunity_ids": list(sched.selected_opportunity_ids),
            "produced_by": sched.produced_by,
        }
    )


def selected_evaluation_digest(run: BenchmarkRun) -> str | None:
    """Bind the COMPLETE canonical selected evaluation (final acceptance, High 1)."""
    q = run.quantum_experiment
    if q is None or q.selected_evaluation is None:
        return None
    ev = q.selected_evaluation
    return sha256_canonical_json(
        {
            "problem_checksum": ev.problem_checksum,
            "selected_opportunity_ids": list(ev.selected_opportunity_ids),
            "feasible": ev.feasible,
            "raw_mission_value": ev.raw_mission_value,
            "weighted_mission_value": ev.weighted_mission_value,
            "constraint_penalty": ev.constraint_penalty,
            "penalized_objective": ev.penalized_objective,
            "objective_value": ev.objective_value,
            "total_energy": ev.total_energy,
            "total_storage": ev.total_storage,
            "violations": sorted([v.kind.value, v.detail, v.magnitude] for v in ev.violations),
            "violations_count": len(ev.violations),
        }
    )


def scientific_metadata_digest(run: BenchmarkRun) -> str:
    """Digest over every material scientific-metadata field (final acceptance, Critical 2):
    solver/quantum/comparison limitations, comparison rationale, epistemic labels, solver/optimality
    status, and the final conclusion. Binding this means ANY change — benign or overclaiming — to a
    caveat or epistemic label after acceptance invalidates read authentication."""
    solvers = sorted(
        [
            r.solver_kind.value,
            r.limitations,
            r.epistemic_status.value,
            r.status.value,
            r.optimality_status.value,
        ]
        for r in run.solver_results
    )
    q = run.quantum_experiment
    quantum = [q.limitations, q.epistemic_status.value, q.status.value] if q is not None else None
    c = run.comparison
    comparison = (
        [c.limitations, c.rationale, c.epistemic_status.value, c.conclusion.value]
        if c is not None
        else None
    )
    return sha256_canonical_json({"solvers": solvers, "quantum": quantum, "comparison": comparison})


def selected_parameter_digest(run: BenchmarkRun) -> str | None:
    q = run.quantum_experiment
    if q is None or q.circuit_metadata is None:
        return None
    return sha256_canonical_json(q.circuit_metadata.best_parameters)


def circuit_metadata_digest(run: BenchmarkRun) -> str | None:
    q = run.quantum_experiment
    if q is None or q.circuit_metadata is None:
        return None
    return sha256_canonical_json(q.circuit_metadata.model_dump(mode="json"))


def software_version_digest(run: BenchmarkRun) -> str | None:
    q = run.quantum_experiment
    if q is None:
        return None
    return sha256_canonical_json(q.software_versions)


_MEDIA_TYPES = {".png": "image/png", ".json": "application/json", ".txt": "text/plain"}


def _media_type_for(path: str) -> str:
    for ext, media in _MEDIA_TYPES.items():
        if path.endswith(ext):
            return media
    return "application/octet-stream"


# The canonical artifact sidecar disclaimer/limitations (final acceptance, High #1). Shared with
# the visualization layer so the sidecar's top-level limitations EXACTLY equals the signed entry.
SIDECAR_ARTIFACT_LIMITATIONS = (
    "model-estimate; bounded simulator benchmark on a tiny fixture. A circuit diagram is "
    "NOT evidence of quantum advantage. Not a production tasking decision."
)
ARTIFACT_EPISTEMIC_STATUS = "model-estimate"
ARTIFACT_VERIFICATION_STATE = "verified"


def canonical_artifact_entry(run: BenchmarkRun, art: dict[str, str]) -> dict[str, Any]:
    """One strict, signed artifact manifest entry (fifth review, High #1; final acceptance) — binds
    the artifact's identity, type, checksum, media type, limitations, epistemic status, and
    verification state to the benchmark/problem/result ownership + evidence/policy anchors.
    Receipt-envelope fields are deliberately excluded (the sidecar carries the receipt separately)
    to keep the digest non-circular."""
    c = run.comparison
    q = run.quantum_experiment
    snap = run.policy_snapshot or {}
    checksum = str(art.get("checksum", ""))
    return {
        "artifact_id": checksum,  # content-addressed identity
        "artifact_type": str(art.get("type", "")),
        "artifact_checksum": checksum,
        "media_type": _media_type_for(str(art.get("path", ""))),
        "limitations": SIDECAR_ARTIFACT_LIMITATIONS,
        "epistemic_status": ARTIFACT_EPISTEMIC_STATUS,
        "verification_state": ARTIFACT_VERIFICATION_STATE,
        "benchmark_id": run.id,
        "problem_id": run.problem_id,
        "problem_checksum": run.problem_checksum,
        "exact_result_id": c.exact_result_id if c is not None else None,
        "greedy_result_id": c.greedy_result_id if c is not None else None,
        "quantum_experiment_id": (
            (c.quantum_experiment_id if c is not None else None)
            or (q.id if q is not None else None)
        ),
        "evidence_manifest_checksum": (
            q.evidence.manifest_checksum if (q is not None and q.evidence is not None) else None
        ),
        "policy_snapshot_checksum": str(snap.get("checksum", "")),
    }


def canonical_artifact_manifest(run: BenchmarkRun) -> list[dict[str, Any]]:
    """The ordered collection of canonical artifact entries the receipt digest is computed over."""
    return [canonical_artifact_entry(run, a) for a in run.artifacts]


def _manifest_digest(manifest: list[dict[str, Any]]) -> str:
    return sha256_canonical_json(
        sorted(manifest, key=lambda e: str(e.get("artifact_checksum", "")))
    )


def artifact_manifest_digest(run: BenchmarkRun) -> str | None:
    if not run.artifacts:
        return None
    return _manifest_digest(canonical_artifact_manifest(run))


def _sample_identity(s: Any | None) -> list[Any] | None:
    if s is None:
        return None
    return [s.bitstring, s.count, s.probability, s.feasible, s.raw_mission_value, s.objective_value]


def worker_output_digest(run: BenchmarkRun) -> str:
    """Canonical digest binding the raw worker output. For a quantum run it covers the full sample
    map, circuit metadata, evidence manifest, status, AND the derived selected feasible/infeasible
    samples, feasible-sample ratio, exact-optimum-in-samples, and objective gap (final acceptance,
    Critical 1); otherwise the classical schedules."""
    q = run.quantum_experiment
    if q is not None:
        return sha256_canonical_json(
            {
                "samples": sample_map_digest(run),
                "circuit": circuit_metadata_digest(run),
                "manifest": q.evidence.manifest_checksum if q.evidence else None,
                "status": q.status.value,
                "total_shots": q.total_shots,
                "best_feasible_sample": _sample_identity(q.best_feasible_sample),
                "best_infeasible_sample": _sample_identity(q.best_infeasible_sample),
                "feasible_sample_ratio": q.feasible_sample_ratio,
                "exact_optimum_in_samples": q.exact_optimum_in_samples,
                "objective_gap": q.objective_gap,
                "distinct_samples": q.distinct_samples,
            }
        )
    return sha256_canonical_json(
        sorted(
            [r.solver_kind.value, list(r.schedule.selected_opportunity_ids) if r.schedule else []]
            for r in run.solver_results
        )
    )


def _config_for(run: BenchmarkRun, kind: SolverKind) -> dict[str, Any] | None:
    for r in run.solver_results:
        if r.solver_kind == kind:
            return r.configuration.model_dump(mode="json")
    return None


def _build_payload(run: BenchmarkRun, signer: EvidenceReceiptSigner) -> ReceiptPayload:
    snap = run.policy_snapshot or {}
    c = run.comparison
    q = run.quantum_experiment
    # A receipt is only ever built for a completed-quantum (eligible) or classical-only run; the
    # service gates this. The worker nonce is copied EXACTLY from the worker — never invented.
    eligible = quantum_execution_receipt_eligible(q)
    if q is not None and not eligible:
        raise ValueError("cannot build a receipt for a non-completed quantum experiment")
    return ReceiptPayload(
        receipt_format_version=RECEIPT_FORMAT_VERSION,
        receipt_id=new_id(),
        benchmark_id=run.id,
        problem_id=run.problem_id,
        problem_checksum=run.problem_checksum,
        policy_id=str(snap.get("policy_id", "")),
        policy_version=str(snap.get("policy_version", "")),
        policy_checksum=str(snap.get("checksum", "")),
        comparison_algorithm_version=str(
            snap.get("comparison_algorithm_version", COMPARISON_ALGORITHM_VERSION)
        ),
        exact_result_id=c.exact_result_id if c else None,
        greedy_result_id=c.greedy_result_id if c else None,
        quantum_experiment_id=q.id if q is not None else None,
        exact_config_checksum=_config_checksum(_config_for(run, SolverKind.EXACT)) or "",
        greedy_config_checksum=_config_checksum(_config_for(run, SolverKind.GREEDY)) or "",
        quantum_config_checksum=(
            sha256_canonical_json(q.configuration.model_dump(mode="json"))
            if q is not None
            else None
        ),
        evidence_manifest_checksum=(q.evidence.manifest_checksum if q and q.evidence else None),
        sample_map_digest=sample_map_digest(run),
        selected_parameter_digest=selected_parameter_digest(run),
        circuit_metadata_digest=circuit_metadata_digest(run),
        software_version_digest=software_version_digest(run),
        artifact_manifest_digest=artifact_manifest_digest(run),
        scientific_metadata_digest=scientific_metadata_digest(run),
        best_feasible_sample_digest=best_feasible_sample_digest(run),
        best_infeasible_sample_digest=best_infeasible_sample_digest(run),
        selected_schedule_digest=selected_schedule_digest(run),
        selected_evaluation_digest=selected_evaluation_digest(run),
        worker_execution_nonce=(q.execution_nonce if eligible and q is not None else None),
        worker_output_digest=worker_output_digest(run),
        issued_at=utcnow().isoformat(),
        signer_key_id=signer.key_id,
        signature_algorithm=signer.algorithm,
    )


def build_receipt(run: BenchmarkRun, *, signer: EvidenceReceiptSigner) -> BenchmarkExecutionReceipt:
    payload = _build_payload(run, signer)
    return BenchmarkExecutionReceipt(
        payload=payload,
        payload_checksum=_payload_checksum(payload),
        signature=signer.sign(_payload_bytes(payload)),
    )


def verify_receipt(
    receipt: BenchmarkExecutionReceipt | None,
    *,
    run: BenchmarkRun,
    signers: dict[str, EvidenceReceiptSigner],
    seen_receipt_ids: set[str] | None = None,
) -> EvidenceReceiptVerification:
    """Independently verify a receipt against the current run. Never raises."""
    reasons: list[str] = []
    if receipt is None:
        return EvidenceReceiptVerification(ok=False, reasons=("absent-receipt",))
    p = receipt.payload
    try:
        if _payload_checksum(p) != receipt.payload_checksum:
            reasons.append("payload-checksum")
        signer = signers.get(p.signer_key_id)
        if signer is None:
            reasons.append("unknown-key-id")
        else:
            expected = signer.sign(_payload_bytes(p))
            if not hmac.compare_digest(expected, receipt.signature):
                reasons.append("signature")
        if p.benchmark_id != run.id:
            reasons.append("benchmark-id")
        if p.problem_id != run.problem_id or p.problem_checksum != run.problem_checksum:
            reasons.append("problem")
        snap = run.policy_snapshot or {}
        if (
            p.policy_id != str(snap.get("policy_id", ""))
            or p.policy_version != str(snap.get("policy_version", ""))
            or p.policy_checksum != str(snap.get("checksum", ""))
        ):
            reasons.append("policy-anchor")
        c = run.comparison
        if c is not None and (
            p.exact_result_id != c.exact_result_id
            or p.greedy_result_id != c.greedy_result_id
            or p.quantum_experiment_id != c.quantum_experiment_id
        ):
            reasons.append("association-ids")
        # Strict signed-field schema (fourth review, High #2): unknown versions/algorithms,
        # malformed timestamps/ids/encodings fail CLOSED — interpreting the signed fields, not
        # merely trusting the HMAC.
        reasons.extend(_strict_schema_reasons(receipt))
        # Recompute every canonical digest from the current run.
        for name, expected_value in (
            ("evidence-manifest", p.evidence_manifest_checksum),
            ("sample-map", p.sample_map_digest),
            ("selected-parameter", p.selected_parameter_digest),
            ("circuit-metadata", p.circuit_metadata_digest),
            ("software-version", p.software_version_digest),
            ("artifact-manifest", p.artifact_manifest_digest),
            ("scientific-metadata", p.scientific_metadata_digest),
            ("best-feasible-sample", p.best_feasible_sample_digest),
            ("best-infeasible-sample", p.best_infeasible_sample_digest),
            ("selected-schedule", p.selected_schedule_digest),
            ("selected-evaluation", p.selected_evaluation_digest),
        ):
            if expected_value != _recompute_digest(run, name):
                reasons.append(f"{name}-digest")
        # Independently recompute the solver/quantum CONFIG checksums from the benchmark — a
        # signed digest string is not trusted on its own.
        exact_cfg = _config_checksum(_config_for(run, SolverKind.EXACT)) or ""
        greedy_cfg = _config_checksum(_config_for(run, SolverKind.GREEDY)) or ""
        if p.exact_config_checksum != exact_cfg:
            reasons.append("exact-config-digest")
        if p.greedy_config_checksum != greedy_cfg:
            reasons.append("greedy-config-digest")
        expected_q = (
            sha256_canonical_json(run.quantum_experiment.configuration.model_dump(mode="json"))
            if run.quantum_experiment is not None
            else None
        )
        if p.quantum_config_checksum != expected_q:
            reasons.append("quantum-config-digest")
        # Worker-nonce binding (fourth review, Critical #1/#4). A receipt that claims a quantum
        # experiment must carry the worker's EXACT valid nonce; a classical-only receipt must
        # carry no nonce. A non-completed quantum experiment is never receipt-eligible.
        q = run.quantum_experiment
        if quantum_execution_receipt_eligible(q):
            assert q is not None
            if not _is_valid_worker_nonce(p.worker_execution_nonce):
                reasons.append("worker-nonce")
            elif p.worker_execution_nonce != q.execution_nonce:
                reasons.append("worker-nonce-mismatch")
        elif q is not None:
            reasons.append("quantum-not-eligible")  # quantum present but not a completed run
        elif p.worker_execution_nonce is not None:
            reasons.append("worker-nonce-unexpected")  # classical-only must have no worker nonce
        if p.worker_output_digest != worker_output_digest(run):
            reasons.append("worker-output-digest")
        if seen_receipt_ids is not None and p.receipt_id in seen_receipt_ids:
            reasons.append("reused-receipt")
    except Exception:  # pragma: no cover - any malformed receipt fails closed
        reasons.append("malformed-receipt")
    return EvidenceReceiptVerification(ok=not reasons, reasons=tuple(sorted(set(reasons))))


# ---- sidecar receipt linkage + detached offline authentication (fourth review, High #1) ----
RECEIPT_ENVELOPE_KEY = "execution_receipt"


ARTIFACT_ENTRY_KEY = "artifact_entry"
ARTIFACT_MANIFEST_KEY = "artifact_manifest"
# The receipt envelope must contain EXACTLY these keys (final acceptance, High #1): a missing key
# or an extra key fails closed, and every duplicated value is cross-checked against the payload.
_REQUIRED_ENVELOPE_FIELDS = (
    "receipt_id",
    "receipt_format_version",
    "payload_checksum",
    "signer_key_id",
    "signature_algorithm",
    "signature",
    "payload",
)


def embed_sidecar_evidence(
    meta: dict[str, Any],
    run: BenchmarkRun,
    art: dict[str, str],
    receipt: BenchmarkExecutionReceipt,
) -> dict[str, Any]:
    """Embed this artifact's canonical entry + the COMPLETE canonical manifest + the signed
    receipt envelope into a sidecar (fifth review, High #1). Offline authentication then proves
    the entry belongs to the signed manifest and that the manifest digest matches the receipt —
    a valid receipt alone is not sufficient."""
    return {
        **meta,
        ARTIFACT_ENTRY_KEY: canonical_artifact_entry(run, art),
        ARTIFACT_MANIFEST_KEY: canonical_artifact_manifest(run),
        RECEIPT_ENVELOPE_KEY: {
            "receipt_id": receipt.payload.receipt_id,
            "receipt_format_version": receipt.payload.receipt_format_version,
            "payload_checksum": receipt.payload_checksum,
            "signer_key_id": receipt.payload.signer_key_id,
            "signature_algorithm": receipt.payload.signature_algorithm,
            "signature": receipt.signature,
            "payload": receipt.payload.model_dump(mode="json"),
        },
    }


def embed_receipt(meta: dict[str, Any], receipt: BenchmarkExecutionReceipt) -> dict[str, Any]:
    """Embed only the signed receipt envelope (used where no per-artifact entry applies)."""
    return {
        **meta,
        RECEIPT_ENVELOPE_KEY: {
            "receipt_id": receipt.payload.receipt_id,
            "receipt_format_version": receipt.payload.receipt_format_version,
            "payload_checksum": receipt.payload_checksum,
            "signer_key_id": receipt.payload.signer_key_id,
            "signature_algorithm": receipt.payload.signature_algorithm,
            "signature": receipt.signature,
            "payload": receipt.payload.model_dump(mode="json"),
        },
    }


def authenticate_sidecar_offline(
    meta: dict[str, Any],
    signers: dict[str, EvidenceReceiptSigner],
    *,
    artifact_checksum: str | None = None,
) -> tuple[bool, str]:
    """Authenticate a sidecar WITHOUT database access (fifth review, High #1). Beyond verifying
    the embedded receipt's HMAC, this PROVES the sidecar's canonical artifact entry is a member
    of the signed artifact manifest and recomputes the artifact-manifest digest, comparing it to
    the receipt payload — so a valid receipt with the wrong manifest entry is rejected. When the
    artifact file checksum is supplied it must equal the entry's checksum."""
    env = meta.get(RECEIPT_ENVELOPE_KEY)
    if not isinstance(env, dict):
        return False, "no-receipt-envelope"
    if set(env) != set(_REQUIRED_ENVELOPE_FIELDS):  # missing OR extra key fails closed
        return False, "incomplete-receipt-envelope"
    try:
        receipt = BenchmarkExecutionReceipt.model_validate(
            {
                "payload": env["payload"],
                "payload_checksum": env["payload_checksum"],
                "signature": env["signature"],
            }
        )
    except Exception:
        return False, "malformed-receipt"
    p = receipt.payload
    # Every duplicated envelope value must match the signed payload (a changed receipt id / signer
    # key id / algorithm / format version in the envelope is rejected).
    if (
        env["receipt_id"] != p.receipt_id
        or env["receipt_format_version"] != p.receipt_format_version
        or env["signer_key_id"] != p.signer_key_id
        or env["signature_algorithm"] != p.signature_algorithm
    ):
        return False, "envelope-payload-mismatch"
    signer = signers.get(p.signer_key_id)
    if signer is None:
        return False, "unknown-key-id"
    if _payload_checksum(p) != receipt.payload_checksum:
        return False, "payload-checksum"
    if not hmac.compare_digest(signer.sign(_payload_bytes(p)), receipt.signature):
        return False, "signature"
    # The sidecar's own declared fields must be bound by the signed receipt payload.
    if (
        meta.get("benchmark_id") != p.benchmark_id
        or meta.get("problem_id") != p.problem_id
        or meta.get("problem_checksum") != p.problem_checksum
        or meta.get("policy_snapshot_checksum") != p.policy_checksum
    ):
        return False, "sidecar-binding"
    ev = meta.get("quantum_evidence")
    if isinstance(ev, dict) and ev.get("manifest_checksum") != p.evidence_manifest_checksum:
        return False, "evidence-binding"
    # Artifact-manifest membership + digest proof (the core of High #1).
    entry = meta.get(ARTIFACT_ENTRY_KEY)
    manifest = meta.get(ARTIFACT_MANIFEST_KEY)
    if not isinstance(entry, dict) or not isinstance(manifest, list):
        return False, "no-artifact-manifest"
    if entry not in manifest:
        return False, "entry-not-in-manifest"
    if _manifest_digest(manifest) != p.artifact_manifest_digest:
        return False, "artifact-manifest-digest"
    if entry.get("benchmark_id") != p.benchmark_id or entry.get("problem_id") != p.problem_id:
        return False, "entry-ownership"
    if artifact_checksum is not None and entry.get("artifact_checksum") != artifact_checksum:
        return False, "artifact-checksum"
    # Every duplicated top-level sidecar field must EXACTLY equal the signed canonical entry — no
    # field may have a default that turns absence into trusted data (final acceptance, High #1).
    duplicated = {
        "artifact_type": entry.get("artifact_type"),
        "checksum": entry.get("artifact_checksum"),
        "limitations": entry.get("limitations"),
        "epistemic_status": entry.get("epistemic_status"),
        "benchmark_id": entry.get("benchmark_id"),
        "problem_id": entry.get("problem_id"),
        "problem_checksum": entry.get("problem_checksum"),
        "policy_snapshot_checksum": entry.get("policy_snapshot_checksum"),
    }
    for sidecar_key, entry_value in duplicated.items():
        if sidecar_key not in meta or meta[sidecar_key] != entry_value:
            return False, "duplicate-field-mismatch"
    return True, "authentic"


def _recompute_digest(run: BenchmarkRun, name: str) -> str | None:
    q = run.quantum_experiment
    if name == "evidence-manifest":
        return q.evidence.manifest_checksum if q and q.evidence else None
    if name == "sample-map":
        return sample_map_digest(run)
    if name == "selected-parameter":
        return selected_parameter_digest(run)
    if name == "circuit-metadata":
        return circuit_metadata_digest(run)
    if name == "software-version":
        return software_version_digest(run)
    if name == "artifact-manifest":
        return artifact_manifest_digest(run)
    if name == "scientific-metadata":
        return scientific_metadata_digest(run)
    if name == "best-feasible-sample":
        return best_feasible_sample_digest(run)
    if name == "best-infeasible-sample":
        return best_infeasible_sample_digest(run)
    if name == "selected-schedule":
        return selected_schedule_digest(run)
    if name == "selected-evaluation":
        return selected_evaluation_digest(run)
    return None  # pragma: no cover
