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


def sample_map_digest(run: BenchmarkRun) -> str | None:
    q = run.quantum_experiment
    if q is None or not q.samples:
        return None
    rows = sorted(
        [s.bitstring, s.count, s.probability, s.feasible, s.objective_value, s.qubo_energy]
        for s in q.samples
    )
    return sha256_canonical_json(rows)


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


def artifact_manifest_digest(run: BenchmarkRun) -> str | None:
    if not run.artifacts:
        return None
    return sha256_canonical_json(
        sorted([a.get("type", ""), a.get("checksum", "")] for a in run.artifacts)
    )


def worker_output_digest(run: BenchmarkRun) -> str:
    """Canonical digest binding the raw worker output. For a quantum run it covers the samples,
    circuit metadata, evidence manifest, and status; otherwise the classical schedules."""
    q = run.quantum_experiment
    if q is not None:
        return sha256_canonical_json(
            {
                "samples": sample_map_digest(run),
                "circuit": circuit_metadata_digest(run),
                "manifest": q.evidence.manifest_checksum if q.evidence else None,
                "status": q.status.value,
                "total_shots": q.total_shots,
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


def embed_receipt(meta: dict[str, Any], receipt: BenchmarkExecutionReceipt) -> dict[str, Any]:
    """Embed the completed signed receipt into a sidecar/summary dict (two-layer model: the
    receipt signs the benchmark evidence; the sidecar then carries the receipt). Public metadata
    only — never the signing secret."""
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
    meta: dict[str, Any], signers: dict[str, EvidenceReceiptSigner]
) -> tuple[bool, str]:
    """Authenticate a sidecar WITHOUT database access (fourth review, High #1): verify the
    embedded receipt's HMAC and that the sidecar's declared material fields are bound by the
    signed receipt payload."""
    env = meta.get(RECEIPT_ENVELOPE_KEY)
    if not isinstance(env, dict):
        return False, "no-receipt-envelope"
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
    return None  # pragma: no cover
