"""Authoritative, server-derived quantum evidence manifest (second Codex review, High #1).

The manifest is derived from the canonical normalized problem, a freshly built QUBO, the
server penalty policy, the installed package versions, and the requested configuration — it
is NOT read back from a persisted record. Persisted/API-provided evidence is a CLAIM that the
verifier compares against this manifest; a coordinated, internally-consistent forgery still
fails because the authoritative fields come from the trusted problem (whose checksum is
independently re-verified), not from the persisted evidence block.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.optimization.models import QuantumEvidence, SchedulingProblem, SolverConfiguration
from orbitmind.optimization.penalties import penalty_policy
from orbitmind.optimization.qubo import build_qubo

ALLOWED_BACKEND = "AerSimulator"

_BIT_ORDER = (
    "qubit i == variable_mapping[i] (index 0 first); Aer measurement strings have "
    "qubit 0 as the RIGHTMOST char and are reversed before decoding"
)
_LIMITATIONS = (
    "Only conflict + mandatory constraints are encoded in the QUBO; resource and "
    "cardinality constraints are enforced solely by deterministic post-verification. "
    "Simulator-only; not evidence of hardware advantage."
)


def software_versions() -> dict[str, str]:
    out: dict[str, str] = {}
    for pkg in ("qiskit", "qiskit-aer"):
        try:
            out[pkg] = version(pkg)
        except PackageNotFoundError:  # pragma: no cover - only when uninstalled
            out[pkg] = "unavailable"
    return out


def _encoded_inventory(problem: SchedulingProblem) -> tuple[list[str], list[str]]:
    c = problem.constraints
    encoded: list[str] = []
    if c.enforce_no_overlap:
        encoded.append("no-overlap (same-satellite time conflicts)")
    if c.mutually_exclusive:
        encoded.append("mutual-exclusion")
    if c.mandatory:
        encoded.append("mandatory")
    unencoded: list[str] = []
    if c.max_observations is not None:
        unencoded.append("max-observations")
    if c.enforce_energy_capacity:
        unencoded.append("energy-capacity")
    if c.enforce_storage_capacity:
        unencoded.append("storage-capacity")
    if c.per_target_limit is not None:
        unencoded.append("per-target-limit")
    if c.min_mission_value is not None:
        unencoded.append("min-mission-value")
    return encoded, unencoded


def manifest_checksum(evidence: QuantumEvidence) -> str:
    """Deterministic checksum over the authoritative evidence fields (excludes itself)."""
    return sha256_canonical_json(
        {
            "problem_checksum": evidence.problem_checksum,
            "qubo_checksum": evidence.qubo_checksum,
            "variable_mapping": list(evidence.variable_mapping),
            "qubit_to_variable": {str(k): v for k, v in sorted(evidence.qubit_to_variable.items())},
            "bit_order": evidence.bit_order,
            "encoded_constraints": list(evidence.encoded_constraints),
            "unencoded_constraints": list(evidence.unencoded_constraints),
            "penalty_value": evidence.penalty_value,
            "penalty_source": evidence.penalty_source,
            "penalty_sufficient": evidence.penalty_sufficient,
            "penalty_satisfying_assignment_exists": evidence.penalty_satisfying_assignment_exists,
            "penalty_proof_status": evidence.penalty_proof_status,
            "penalty_proof_method": evidence.penalty_proof_method,
            "simulator_backend": evidence.simulator_backend,
            "seeds": {k: evidence.seeds[k] for k in sorted(evidence.seeds)},
            "software_versions": {
                k: evidence.software_versions[k] for k in sorted(evidence.software_versions)
            },
        }
    )


def build_evidence_manifest(
    problem: SchedulingProblem, config: SolverConfiguration
) -> QuantumEvidence:
    """The authoritative manifest derived from the trusted problem + server config + policy."""
    qubo = build_qubo(problem)
    pol = penalty_policy(problem)
    encoded, unencoded = _encoded_inventory(problem)
    base = QuantumEvidence(
        problem_checksum=problem.checksum,
        qubo_checksum=qubo.checksum,
        variable_mapping=qubo.variable_opportunities,
        qubit_to_variable=dict(enumerate(qubo.variable_opportunities)),
        bit_order=_BIT_ORDER,
        encoded_constraints=tuple(encoded),
        unencoded_constraints=tuple(unencoded),
        penalty_value=pol.penalty,
        penalty_source=pol.source,
        penalty_sufficient=pol.sufficient,
        penalty_satisfying_assignment_exists=pol.satisfying_encoded_assignment_exists,
        penalty_proof_status=pol.proof_status.value,
        penalty_proof_method=pol.method,
        simulator_backend=ALLOWED_BACKEND,
        seeds={
            "seed": config.seed,
            "seed_simulator": config.seed,
            "seed_transpiler": config.seed,
        },
        software_versions=software_versions(),
        limitations=_LIMITATIONS,
    )
    return base.model_copy(update={"manifest_checksum": manifest_checksum(base)})


def evidence_matches_manifest(
    claim: QuantumEvidence, manifest: QuantumEvidence
) -> tuple[bool, str]:
    """Compare a persisted evidence CLAIM to the authoritative manifest. Returns (ok, reason)."""
    checks: dict[str, bool] = {
        "problem_checksum": claim.problem_checksum == manifest.problem_checksum,
        "qubo_checksum": claim.qubo_checksum == manifest.qubo_checksum,
        "variable_mapping": tuple(claim.variable_mapping) == tuple(manifest.variable_mapping),
        "qubit_to_variable": dict(claim.qubit_to_variable) == dict(manifest.qubit_to_variable),
        "bit_order": claim.bit_order == manifest.bit_order,
        "encoded_constraints": tuple(claim.encoded_constraints)
        == tuple(manifest.encoded_constraints),
        "unencoded_constraints": tuple(claim.unencoded_constraints)
        == tuple(manifest.unencoded_constraints),
        "penalty_value": claim.penalty_value == manifest.penalty_value,
        "penalty_source": claim.penalty_source == manifest.penalty_source,
        "penalty_sufficient": claim.penalty_sufficient == manifest.penalty_sufficient,
        "penalty_proof_status": claim.penalty_proof_status == manifest.penalty_proof_status,
        "simulator_backend": claim.simulator_backend == manifest.simulator_backend,
        "seeds": dict(claim.seeds) == dict(manifest.seeds),
        "software_versions": dict(claim.software_versions) == dict(manifest.software_versions),
        "manifest_checksum": claim.manifest_checksum == manifest.manifest_checksum,
    }
    failed = sorted(k for k, ok in checks.items() if not ok)
    return (not failed), ("authentic" if not failed else f"mismatch: {', '.join(failed)}")
