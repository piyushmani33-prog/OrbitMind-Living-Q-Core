"""Benchmark-parent policy snapshot anchoring (third Codex review, High #3).

The requested policy is anchored on the benchmark PARENT; a comparison-only coherent swap is
rejected, and a persisted snapshot stays verifiable after a controlled registry retirement.
"""

from __future__ import annotations

from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.models import BenchmarkRun
from orbitmind.optimization.policy import (
    default_policy,
    get_policy,
    is_active,
    snapshot_is_self_consistent,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark

_PROBLEM = normalize_problem(fixtures.fixture("default"))


def _run() -> BenchmarkRun:
    return run_benchmark(_PROBLEM, seed=7, run_quantum=False)  # default policy = strict-v1


def _findings(run: BenchmarkRun) -> dict[str, bool]:
    return {f.check_id: f.passed for f in verify_benchmark(_PROBLEM, run)}


def test_untampered_run_has_parent_policy_anchor() -> None:
    run = _run()
    assert run.policy_snapshot is not None and run.policy_snapshot["policy_id"] == "strict-v1"
    f = _findings(run)
    assert f["opt.parent_policy_snapshot"] and f["opt.comparison_matches_parent_policy"]
    assert all_critical_passed(verify_benchmark(_PROBLEM, run))


def test_coherent_comparison_policy_swap_is_rejected_by_parent() -> None:
    run = _run()
    lenient = get_policy("lenient-v1")
    assert lenient is not None and run.comparison is not None
    # Coherently rewrite EVERY comparison policy field strict-v1 -> lenient-v1. The parent still
    # says strict-v1, so the parent-anchor check rejects it.
    comp = run.comparison.model_copy(
        update={
            "policy_id": lenient.policy_id,
            "policy_version": lenient.policy_version,
            "policy_checksum": lenient.checksum,
            "thresholds": lenient.thresholds(),
        }
    )
    tampered = run.model_copy(update={"comparison": comp})
    f = _findings(tampered)
    assert not f["opt.comparison_matches_parent_policy"]
    assert not all_critical_passed(verify_benchmark(_PROBLEM, tampered))


def test_tampered_parent_snapshot_is_rejected() -> None:
    run = _run()
    assert run.policy_snapshot is not None
    # Modify a snapshot field without updating its checksum: self-consistency fails.
    bad = dict(run.policy_snapshot)
    bad["competitive_relative_gap"] = 0.9
    tampered = run.model_copy(update={"policy_snapshot": bad})
    assert not _findings(tampered)["opt.parent_policy_snapshot"]


def test_missing_parent_snapshot_is_rejected() -> None:
    run = _run().model_copy(update={"policy_snapshot": None})
    assert not _findings(run)["opt.parent_policy_snapshot"]


def test_snapshot_self_consistency_and_retirement() -> None:
    snap = default_policy().model_dump(mode="json")
    assert snapshot_is_self_consistent(snap)
    # A modified snapshot (checksum no longer matches its fields) is not self-consistent.
    snap_bad = {**snap, "min_feasible_sample_ratio": 0.99}
    assert not snapshot_is_self_consistent(snap_bad)
    assert not snapshot_is_self_consistent(None)
    # Active vs retired registry reporting.
    assert is_active("strict-v1") and not is_active("retired-policy-x")


def test_retired_policy_snapshot_still_self_verifies() -> None:
    # A snapshot whose policy_id is NOT in the active registry still validates via its own
    # checksum (historical verification does not depend on the registry).
    from orbitmind.optimization.policy import ComparisonPolicy, policy_checksum

    retired = ComparisonPolicy(
        policy_id="retired-2024",
        policy_version="1",
        competitive_relative_gap=0.1,
        min_feasible_sample_ratio=0.2,
    )
    retired = retired.model_copy(update={"checksum": policy_checksum(retired)})
    assert not is_active("retired-2024")
    assert snapshot_is_self_consistent(retired.model_dump(mode="json"))
