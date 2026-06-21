"""Server-owned comparison-policy registry (second Codex review, High finding #2 / #9).

Comparison thresholds and policy versions are NOT trusted from the persisted comparison
record. They come from this immutable, server-owned registry. The verifier reconstructs the
expected policy by id and authenticates the persisted policy id / version / checksum /
thresholds against it, then re-derives the conclusion using the SERVER thresholds — so
coherently changing both a persisted threshold and the conclusion is rejected.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.optimization.models import BenchmarkThresholds

COMPARISON_ALGORITHM_VERSION = "1.0"


class ComparisonPolicy(BaseModel):
    """An immutable, server-owned benchmark comparison policy with a deterministic checksum."""

    model_config = ConfigDict(frozen=True)

    policy_id: str
    policy_version: str
    competitive_relative_gap: float
    min_feasible_sample_ratio: float
    comparison_algorithm_version: str = COMPARISON_ALGORITHM_VERSION
    checksum: str = ""

    def thresholds(self) -> BenchmarkThresholds:
        return BenchmarkThresholds(
            competitive_relative_gap=self.competitive_relative_gap,
            min_feasible_sample_ratio=self.min_feasible_sample_ratio,
        )


def policy_checksum(policy: ComparisonPolicy) -> str:
    return sha256_canonical_json(
        {
            "policy_id": policy.policy_id,
            "policy_version": policy.policy_version,
            "competitive_relative_gap": policy.competitive_relative_gap,
            "min_feasible_sample_ratio": policy.min_feasible_sample_ratio,
            "comparison_algorithm_version": policy.comparison_algorithm_version,
        }
    )


def _make(policy_id: str, version: str, gap: float, ratio: float) -> ComparisonPolicy:
    base = ComparisonPolicy(
        policy_id=policy_id,
        policy_version=version,
        competitive_relative_gap=gap,
        min_feasible_sample_ratio=ratio,
    )
    return base.model_copy(update={"checksum": policy_checksum(base)})


# Closed registry. A persisted comparison may only reference one of these ids; arbitrary
# client-supplied thresholds are NOT accepted (the verifier cannot authenticate them).
_REGISTRY: dict[str, ComparisonPolicy] = {
    p.policy_id: p
    for p in (
        _make("strict-v1", "1", 0.0, 0.05),
        _make("lenient-v1", "1", 0.25, 0.33),
    )
}

DEFAULT_POLICY_ID = "strict-v1"


def get_policy(policy_id: str) -> ComparisonPolicy | None:
    return _REGISTRY.get(policy_id)


def default_policy() -> ComparisonPolicy:
    return _REGISTRY[DEFAULT_POLICY_ID]


def is_active(policy_id: str) -> bool:
    """Whether a policy id is still in the active registry (False once retired)."""
    return policy_id in _REGISTRY


def snapshot_is_self_consistent(snapshot: dict[str, object] | None) -> bool:
    """A persisted policy snapshot validates against ITS OWN checksum (historical anchor).

    This does not require the registry to still contain the policy, so an old benchmark stays
    verifiable after a controlled policy retirement (third review, High #3 / finding #9).
    """
    if not snapshot:
        return False
    try:
        pol = ComparisonPolicy.model_validate(snapshot)
        return bool(pol.checksum) and pol.checksum == policy_checksum(pol)
    except Exception:
        return False


def available_policy_ids() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def authenticate_policy(
    *,
    policy_id: str,
    policy_version: str,
    policy_checksum_value: str,
    thresholds: BenchmarkThresholds,
) -> tuple[ComparisonPolicy | None, bool, str]:
    """Reconstruct the expected policy from the registry and compare the persisted claim.

    Returns (authoritative_policy, ok, explanation). ``authoritative_policy`` is the server
    policy to use for re-deriving the conclusion (None when the id is unknown).
    """
    expected = _REGISTRY.get(policy_id)
    if expected is None:
        return None, False, f"unknown comparison policy id '{policy_id}'"
    ok = (
        expected.policy_version == policy_version
        and expected.checksum == policy_checksum_value
        and abs(expected.competitive_relative_gap - thresholds.competitive_relative_gap) < 1e-12
        and abs(expected.min_feasible_sample_ratio - thresholds.min_feasible_sample_ratio) < 1e-12
    )
    return expected, ok, "policy authenticated" if ok else "policy mismatch vs server registry"
