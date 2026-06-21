"""Tamper-resistant, deterministic verification of benchmark results (review finding #2).

The verifier RE-COMPUTES authoritative values from canonical inputs (the problem, the
re-solved exact/greedy schedules, the QUBO, the observed sample counts, and the actual
artifact files on disk) instead of confirming that internally-supplied result fields agree
with one another. A persisted value is never treated as proof of itself. Any failed
material (CRITICAL/ERROR) check means the benchmark is NOT verified and must not be marked
successful, competitive, or registered to memory.
"""

from __future__ import annotations

import json
import math
from itertools import product
from pathlib import Path
from typing import Any

from orbitmind.core.checksums import sha256_file
from orbitmind.core.paths import ensure_within
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.optimization.benchmark import conclude, proven_optimum
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.evidence import build_evidence_manifest, evidence_matches_manifest
from orbitmind.optimization.models import (
    BenchmarkRun,
    ExperimentStatus,
    OptimalityStatus,
    PenaltyProofStatus,
    QuantumExperiment,
    SchedulingProblem,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.penalties import penalty_policy
from orbitmind.optimization.policy import authenticate_policy, default_policy
from orbitmind.optimization.problem import problem_checksum, variable_order
from orbitmind.optimization.qubo import build_qubo, qubo_energy
from orbitmind.optimization.solvers import solve_exact, solve_greedy
from orbitmind.verification.models import (
    CheckCategory,
    FindingStatus,
    Severity,
    VerificationFinding,
)

_EXHAUSTIVE_MAX_VARS = 16
_TOL = 1e-9
_BOUNDED_EPISTEMIC = {EpistemicStatus.MODEL_ESTIMATE.value, EpistemicStatus.HYPOTHESIS.value}


def _num(value: float | None) -> float:
    """None -> NaN for tolerance comparisons; a genuine 0.0 stays 0.0 (review finding #18).

    ``value or math.nan`` is wrong because ``0.0 or math.nan`` evaluates to NaN, corrupting a
    valid zero objective. Use an explicit ``is None`` check.
    """
    return value if value is not None else math.nan


def _f(
    check_id: str,
    ok: bool,
    explanation: str,
    *,
    category: CheckCategory,
    severity: Severity = Severity.ERROR,
    values: dict[str, Any] | None = None,
) -> VerificationFinding:
    return VerificationFinding(
        check_id=check_id,
        severity=severity if not ok else Severity.INFO,
        status=FindingStatus.PASSED if ok else FindingStatus.FAILED,
        explanation=explanation,
        category=category,
        values=values or {},
    )


def verify_benchmark(
    problem: SchedulingProblem,
    run: BenchmarkRun,
    *,
    artifacts_root: Path | None = None,
) -> list[VerificationFinding]:
    """Independently re-verify a benchmark run. Returns findings (no failures == clean)."""
    findings: list[VerificationFinding] = []
    evaluator = Evaluator(problem)
    order = variable_order(problem)
    valid_ids = set(order)

    # 1. Canonical problem checksum recomputed from content.
    recomputed_checksum = problem_checksum(problem)
    findings.append(
        _f(
            "opt.problem_checksum",
            recomputed_checksum == problem.checksum,
            "problem checksum recomputed from canonical content matches the stored checksum",
            category=CheckCategory.PROVENANCE,
            severity=Severity.CRITICAL,
            values={"stored": problem.checksum, "recomputed": recomputed_checksum},
        )
    )
    # Same-instance: every record's checksum equals the recomputed one.
    instance_checksums = {run.problem_checksum} | {r.problem_checksum for r in run.solver_results}
    if run.quantum_experiment is not None:
        instance_checksums.add(run.quantum_experiment.problem_checksum)
    if run.comparison is not None:
        instance_checksums.add(run.comparison.problem_checksum)
    findings.append(
        _f(
            "opt.same_instance",
            instance_checksums == {recomputed_checksum},
            "every solver/experiment/comparison ran the SAME recomputed problem instance",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"checksums": sorted(instance_checksums)},
        )
    )

    # 2-11. QUBO + penalty + exhaustive energy equivalence (recomputed).
    qubo = build_qubo(problem)
    findings.append(
        _f(
            "opt.qubo_variable_order",
            qubo.variable_opportunities == order,
            "QUBO variable order preserved (canonical sorted-id ordering, index 0 first)",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
        )
    )
    policy = penalty_policy(problem)
    findings.append(
        _f(
            "opt.penalty_policy",
            policy.proof_status
            in (PenaltyProofStatus.PROVEN_SUFFICIENT, PenaltyProofStatus.NOT_APPLICABLE)
            and policy.satisfying_encoded_assignment_exists,
            f"penalty P={policy.penalty} proof status '{policy.proof_status.value}' "
            f"({policy.method}); a satisfying encoded assignment exists",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
            values=policy.model_dump(),
        )
    )
    if qubo.num_vars <= _EXHAUSTIVE_MAX_VARS:
        mism = sum(
            1
            for bt in product("01", repeat=qubo.num_vars)
            if abs(
                qubo_energy(qubo, "".join(bt))
                + evaluator.evaluate_bitstring("".join(bt)).penalized_objective
            )
            > _TOL
        )
        findings.append(
            _f(
                "opt.qubo_energy_equivalence",
                mism == 0,
                "QUBO energy == -penalized_objective for ALL bitstrings (recomputed)",
                category=CheckCategory.MATHEMATICS,
                severity=Severity.CRITICAL,
                values={"mismatches": mism},
            )
        )

    # 3-8. Re-solve exact + greedy independently; the reported results must match truth.
    trusted_exact = solve_exact(
        problem, SolverConfiguration(solver_kind=SolverKind.EXACT, timeout_seconds=60.0), evaluator
    )
    trusted_greedy = solve_greedy(
        problem, SolverConfiguration(solver_kind=SolverKind.GREEDY, timeout_seconds=60.0), evaluator
    )
    trusted = {SolverKind.EXACT: trusted_exact, SolverKind.GREEDY: trusted_greedy}
    findings.extend(_verify_solvers(run, trusted, evaluator, valid_ids))
    findings.extend(_verify_baselines(run, problem, trusted_exact, trusted_greedy, len(order)))
    findings.extend(_verify_ownership(run, problem))

    # 12-22. Quantum experiment recomputation.
    if run.quantum_experiment is not None:
        findings.extend(_verify_quantum(run.quantum_experiment, evaluator, problem, trusted_exact))

    # 23. Comparison fields + conclusion re-derived from the trusted results.
    findings.extend(_verify_comparison(run, trusted_exact, trusted_greedy))

    # 24-28. Artifacts: containment, existence, checksum, sidecar, bounded metadata.
    if artifacts_root is not None and run.artifacts:
        findings.extend(_verify_artifacts(run, artifacts_root, recomputed_checksum))

    return findings


def _verify_solvers(
    run: BenchmarkRun,
    trusted: dict[SolverKind, SolverResult],
    evaluator: Evaluator,
    valid_ids: set[str],
) -> list[VerificationFinding]:
    out: list[VerificationFinding] = []
    for result in run.solver_results:
        kind = result.solver_kind
        # An unsupported/unknown classical solver kind (e.g. a fabricated or quantum kind in the
        # classical results) yields a deterministic CRITICAL finding instead of a KeyError on the
        # trusted-baseline lookup (review finding #18).
        trusted_result = trusted.get(kind)
        if trusted_result is None:
            out.append(
                _f(
                    f"opt.unsupported_solver_kind.{kind.value}",
                    False,
                    f"comparison contains an unsupported classical solver kind '{kind.value}'",
                    category=CheckCategory.STRUCTURE,
                    severity=Severity.CRITICAL,
                )
            )
            continue
        if result.schedule is None or result.evaluation is None:
            continue
        selected = set(result.schedule.selected_opportunity_ids)
        out.append(
            _f(
                f"opt.selected_exist.{kind.value}",
                selected <= valid_ids,
                f"{result.solver_name}: all selected opportunities exist in the problem",
                category=CheckCategory.STRUCTURE,
                severity=Severity.CRITICAL,
            )
        )
        # Independent re-evaluation of the reported schedule (raw/weighted/penalty/objective).
        recomputed = evaluator.evaluate(selected)
        consistent = (
            abs(recomputed.objective_value - _num(result.objective_value)) < _TOL
            and recomputed.feasible == result.feasible
        )
        out.append(
            _f(
                f"opt.objective_recompute.{kind.value}",
                consistent,
                f"{result.solver_name}: objective + feasibility re-verified from the schedule",
                category=CheckCategory.MATHEMATICS,
                severity=Severity.CRITICAL,
                values={
                    "reported_objective": result.objective_value,
                    "recomputed_objective": recomputed.objective_value,
                    "reported_feasible": result.feasible,
                    "recomputed_feasible": recomputed.feasible,
                },
            )
        )
        # The reported result must match an INDEPENDENT re-solve (catches tampered
        # selected-schedule / objective / optimality status).
        t = trusted_result
        truth_obj = t.objective_value if t.feasible else None
        if kind == SolverKind.EXACT:
            opt_truth, _sel = proven_optimum(t)
            matches_truth = (
                result.feasible == t.feasible
                and abs(_num(result.objective_value) - _num(truth_obj)) < _TOL
                and result.optimality_status == t.optimality_status
                and (
                    result.known_optimum is None
                    or abs(result.known_optimum - _num(opt_truth)) < _TOL
                )
            )
            out.append(
                _f(
                    "opt.exact_matches_independent_resolve",
                    matches_truth,
                    "reported exact objective/optimality/known-optimum match a re-solve",
                    category=CheckCategory.MATHEMATICS,
                    severity=Severity.CRITICAL,
                    values={
                        "reported_objective": result.objective_value,
                        "trusted_objective": truth_obj,
                        "reported_optimality": result.optimality_status.value,
                        "trusted_optimality": t.optimality_status.value,
                        "reported_known_optimum": result.known_optimum,
                    },
                )
            )
        out.append(
            _f(
                f"opt.seed_recorded.{kind.value}",
                isinstance(result.seed, int),
                f"{result.solver_name}: seed recorded",
                category=CheckCategory.PROVENANCE,
                severity=Severity.WARNING,
            )
        )
    return out


def _verify_quantum(
    qexp: QuantumExperiment,
    evaluator: Evaluator,
    problem: SchedulingProblem,
    trusted_exact: SolverResult,
) -> list[VerificationFinding]:
    out: list[VerificationFinding] = []
    # Quantum EVIDENCE checks apply only to a COMPLETED experiment. A non-completed run
    # (unsupported / failed / timed-out / cancelled) carries no positive evidence and is
    # handled as non-positive by the comparison policy; there is nothing to re-verify.
    if qexp.status != ExperimentStatus.COMPLETED:
        out.append(
            _f(
                "opt.quantum_non_completed_no_positive",
                qexp.best_feasible_sample is None and qexp.circuit_metadata is None,
                f"non-completed quantum status '{qexp.status.value}' carries no completed evidence",
                category=CheckCategory.POLICY,
            )
        )
        return out

    qubo = build_qubo(problem)
    n = len(variable_order(problem))

    # Authenticate the persisted evidence against the server-derived manifest (review #1):
    # the manifest is rebuilt from the trusted problem + config, NOT read back from the record.
    manifest = build_evidence_manifest(problem, qexp.configuration)
    ev_claim = qexp.evidence
    ev_ok, ev_reason = (
        evidence_matches_manifest(ev_claim, manifest)
        if ev_claim is not None
        else (False, "missing")
    )
    out.append(
        _f(
            "opt.quantum_evidence_authentic",
            ev_ok,
            f"persisted quantum evidence matches the server-derived manifest ({ev_reason})",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"manifest_checksum": manifest.manifest_checksum},
        )
    )

    # The authoritative shot count comes from the server configuration, not the persisted
    # total_shots — so doubling counts AND total_shots together is still rejected.
    expected_shots = min(qexp.configuration.shots, problem.limits.max_shots)

    # Per-sample independent re-evaluation + binary/width validity.
    sample_ok = True
    prob_ok = True
    counts_positive = True
    scalars_finite = True
    total = 0
    feasible_shots = 0
    recomputed_best_feasible = None
    recomputed_best_infeasible = None
    seen_bitstrings: set[str] = set()
    for s in qexp.samples:
        seen_bitstrings.add(s.bitstring)
        # Strict scalar typing (third review, Medium #1): the count must be a real int (a bool
        # is rejected because ``type(True) is int`` is False), positive, never a float.
        if type(s.count) is not int or s.count <= 0:
            counts_positive = False
            total += s.count if isinstance(s.count, int) else 0
        else:
            total += s.count
        # Every persisted scalar must be finite (reject NaN/inf in probability/objective/energy/
        # raw mission value); these produce findings, never exceptions.
        if not all(
            math.isfinite(x)
            for x in (s.probability, s.objective_value, s.qubo_energy, s.raw_mission_value)
        ):
            scalars_finite = False
        if len(s.bitstring) != n or any(c not in "01" for c in s.bitstring):
            sample_ok = False
            continue
        ev = evaluator.evaluate_bitstring(s.bitstring)
        energy = qubo_energy(qubo, s.bitstring)
        if (
            ev.feasible != s.feasible
            or abs(ev.objective_value - s.objective_value) > _TOL
            or abs(energy - s.qubo_energy) > _TOL
            or len(ev.violations) != s.violations_count
        ):
            sample_ok = False
        if s.feasible:
            feasible_shots += s.count
            if recomputed_best_feasible is None or (s.objective_value, s.count, s.bitstring) > (
                recomputed_best_feasible.objective_value,
                recomputed_best_feasible.count,
                recomputed_best_feasible.bitstring,
            ):
                recomputed_best_feasible = s
        else:
            if recomputed_best_infeasible is None or (s.qubo_energy, -s.count, s.bitstring) < (
                recomputed_best_infeasible.qubo_energy,
                -recomputed_best_infeasible.count,
                recomputed_best_infeasible.bitstring,
            ):
                recomputed_best_infeasible = s
    for s in qexp.samples:  # per-sample probability recomputed from count/total
        if total and abs(s.probability - s.count / total) > 1e-6:
            prob_ok = False

    out.append(
        _f(
            "opt.quantum_samples_reverified",
            sample_ok,
            "every sample re-decoded (valid binary width) with matching feasibility + energy",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
        )
    )
    out.append(
        _f(
            "opt.quantum_probabilities",
            prob_ok,
            "each reported per-sample probability equals count / total_shots",
            category=CheckCategory.MATHEMATICS,
        )
    )
    out.append(
        _f(
            "opt.quantum_counts_positive",
            counts_positive,
            "every stored sample has a strict positive int count (no bool/float/zero/negative)",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
        )
    )
    # Finiteness of every persisted scalar (samples + circuit params + runtime). NaN/inf -> finding.
    meta_params_finite = qexp.circuit_metadata is None or all(
        math.isfinite(v) for v in qexp.circuit_metadata.best_parameters.values()
    )
    out.append(
        _f(
            "opt.quantum_scalars_finite",
            scalars_finite
            and meta_params_finite
            and math.isfinite(qexp.runtime_seconds)
            and (qexp.objective_gap is None or math.isfinite(qexp.objective_gap)),
            "all sample/parameter/runtime scalars are finite (no NaN or infinity)",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
        )
    )
    out.append(
        _f(
            "opt.quantum_bitstrings_unique",
            len(seen_bitstrings) == len(qexp.samples),
            "stored sample bitstrings are unique after canonical normalization",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
            values={"distinct": len(seen_bitstrings), "stored": len(qexp.samples)},
        )
    )
    out.append(
        _f(
            "opt.quantum_shot_total",
            type(qexp.total_shots) is int
            and total == qexp.total_shots == expected_shots
            and expected_shots > 0,
            "sample counts sum to a positive-int total_shots AND the server-configured shots",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
            values={"sum": total, "reported": qexp.total_shots, "expected": expected_shots},
        )
    )
    out.append(
        _f(
            "opt.quantum_metadata_shots",
            qexp.circuit_metadata is not None and qexp.circuit_metadata.shots == expected_shots,
            "circuit-metadata shot count equals the server-configured shot count",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
            values={"metadata": qexp.circuit_metadata.shots if qexp.circuit_metadata else None},
        )
    )
    out.append(
        _f(
            "opt.quantum_distinct_samples",
            len(qexp.samples) == qexp.distinct_samples,
            "distinct-sample count matches the number of samples",
            category=CheckCategory.STRUCTURE,
        )
    )
    expected_ratio = feasible_shots / total if total else 0.0
    out.append(
        _f(
            "opt.quantum_feasible_ratio",
            abs(expected_ratio - qexp.feasible_sample_ratio) < 1e-6,
            "feasible-sample ratio recomputed from samples matches the reported ratio",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
            values={"recomputed": expected_ratio, "reported": qexp.feasible_sample_ratio},
        )
    )
    # Best feasible/infeasible recomputed from observed samples.
    rep_bf = qexp.best_feasible_sample
    best_feasible_ok = (rep_bf is None) == (recomputed_best_feasible is None)
    if rep_bf is not None and recomputed_best_feasible is not None:
        best_feasible_ok = (
            best_feasible_ok and rep_bf.bitstring == recomputed_best_feasible.bitstring
        )
    out.append(
        _f(
            "opt.quantum_best_feasible",
            best_feasible_ok,
            "reported best-feasible sample matches the best feasible OBSERVED sample",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
        )
    )
    if rep_bf is not None:
        out.append(
            _f(
                "opt.quantum_selected_observed",
                rep_bf.bitstring in seen_bitstrings,
                "selected quantum sample was actually observed in the shot results",
                category=CheckCategory.STRUCTURE,
                severity=Severity.CRITICAL,
            )
        )
        out.append(
            _f(
                "opt.quantum_selected_schedule",
                qexp.selected_schedule is not None
                and qexp.selected_schedule.selected_opportunity_ids
                == evaluator.evaluate_bitstring(rep_bf.bitstring).selected_opportunity_ids,
                "selected schedule decodes from the selected sample under the canonical bit order",
                category=CheckCategory.MATHEMATICS,
                severity=Severity.CRITICAL,
            )
        )
    # Objective gap + optimum-in-samples ONLY when a proven optimum exists (finding #10/#20).
    opt_value, opt_sel = proven_optimum(trusted_exact)
    if opt_value is None:
        out.append(
            _f(
                "opt.quantum_gap_absent_without_optimum",
                qexp.objective_gap is None and qexp.exact_optimum_in_samples is None,
                "objective gap + optimum-in-samples are absent when no optimum is proven",
                category=CheckCategory.POLICY,
                severity=Severity.CRITICAL,
            )
        )
    else:
        expected_gap = (opt_value - rep_bf.objective_value) if rep_bf is not None else None
        gap_ok = (qexp.objective_gap is None and rep_bf is None) or (
            qexp.objective_gap is not None
            and expected_gap is not None
            and abs(qexp.objective_gap - expected_gap) < _TOL
        )
        out.append(
            _f(
                "opt.quantum_objective_gap",
                gap_ok,
                "objective gap recomputed against the proven optimum matches the reported gap",
                category=CheckCategory.MATHEMATICS,
                values={"expected": expected_gap, "reported": qexp.objective_gap},
            )
        )
        opt_bits = evaluator.evaluate(set(opt_sel)).selected_opportunity_ids if opt_sel else None
        observed_opt = any(
            len(s.bitstring) == n
            and all(ch in "01" for ch in s.bitstring)
            and s.feasible
            and evaluator.evaluate_bitstring(s.bitstring).selected_opportunity_ids == opt_bits
            for s in qexp.samples
        )
        out.append(
            _f(
                "opt.quantum_optimum_in_samples",
                qexp.exact_optimum_in_samples == observed_opt,
                "exact-optimum-in-samples flag recomputed from the observed samples",
                category=CheckCategory.MATHEMATICS,
            )
        )
    # Seeds + simulator-only.
    meta = qexp.circuit_metadata
    out.append(
        _f(
            "opt.quantum_seeds_recorded",
            meta is not None
            and isinstance(meta.seed_simulator, int)
            and isinstance(meta.seed_transpiler, int)
            and meta.seed_simulator == qexp.configuration.seed,
            "simulator + transpiler seeds recorded and consistent with the configuration",
            category=CheckCategory.PROVENANCE,
            severity=Severity.CRITICAL,
        )
    )
    out.append(
        _f(
            "opt.quantum_simulator_only",
            meta is not None and meta.simulator_backend == "AerSimulator",
            "quantum experiment is simulator-only (Aer; no hardware)",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"backend": meta.simulator_backend if meta else None},
        )
    )
    out.append(
        _f(
            "opt.quantum_bounded_epistemic",
            qexp.epistemic_status.value in _BOUNDED_EPISTEMIC and bool(qexp.limitations.strip()),
            "quantum experiment carries a bounded epistemic status + non-empty limitations",
            category=CheckCategory.POLICY,
        )
    )
    return out


def _verify_baselines(
    run: BenchmarkRun,
    problem: SchedulingProblem,
    trusted_exact: SolverResult,
    trusted_greedy: SolverResult,
    n: int,
) -> list[VerificationFinding]:
    """Authenticate the classical baseline cardinality + the exact/greedy records (High #2)."""
    out: list[VerificationFinding] = []
    exact_results = [r for r in run.solver_results if r.solver_kind == SolverKind.EXACT]
    greedy_results = [r for r in run.solver_results if r.solver_kind == SolverKind.GREEDY]
    ids = [r.id for r in run.solver_results]
    out.append(
        _f(
            "opt.baseline_cardinality",
            len(run.solver_results) == 2
            and len(exact_results) == 1
            and len(greedy_results) == 1
            and len(set(ids)) == len(ids),
            "exactly one exact + one greedy classical baseline (no duplicates / extra kinds)",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
            values={
                "exact": len(exact_results),
                "greedy": len(greedy_results),
                "total": len(run.solver_results),
            },
        )
    )
    # When the trusted re-solve proves an optimum (tiny instances always complete), the reported
    # exact/greedy baselines must themselves be COMPLETED — a failed/timed-out/cancelled record
    # with otherwise-consistent fields must not pass (review findings #7/#8).
    trusted_exact_proven = (
        trusted_exact.status == ExperimentStatus.COMPLETED
        and trusted_exact.optimality_status == OptimalityStatus.OPTIMAL
    )
    if exact_results and trusted_exact_proven:
        ex0 = exact_results[0]
        out.append(
            _f(
                "opt.exact_status_completed",
                ex0.status == ExperimentStatus.COMPLETED
                and ex0.optimality_status == OptimalityStatus.OPTIMAL
                and ex0.feasible,
                "exact baseline is completed, proven-optimal, and feasible",
                category=CheckCategory.STRUCTURE,
                severity=Severity.CRITICAL,
                values={"status": ex0.status.value, "optimality": ex0.optimality_status.value},
            )
        )
    if greedy_results and trusted_greedy.status == ExperimentStatus.COMPLETED:
        g0 = greedy_results[0]
        out.append(
            _f(
                "opt.greedy_status_completed",
                g0.status == ExperimentStatus.COMPLETED,
                "greedy baseline status is completed",
                category=CheckCategory.STRUCTURE,
                severity=Severity.CRITICAL,
                values={"status": g0.status.value},
            )
        )
    # Authenticate the exact baseline's exhaustive candidate count (2^n) for a proven optimum.
    if exact_results:
        ex = exact_results[0]
        proven = (
            ex.status == ExperimentStatus.COMPLETED
            and ex.optimality_status == OptimalityStatus.OPTIMAL
        )
        if proven and n <= problem.limits.exact_max_variables:
            out.append(
                _f(
                    "opt.exact_exhaustive_candidate_count",
                    ex.resource_usage.evaluated_candidates == (1 << n),
                    f"a proven-optimal exhaustive exact solve must evaluate 2^{n} candidates",
                    category=CheckCategory.MATHEMATICS,
                    severity=Severity.CRITICAL,
                    values={
                        "evaluated": ex.resource_usage.evaluated_candidates,
                        "expected": 1 << n,
                    },
                )
            )
    # Authenticate the greedy baseline against a deterministic rerun.
    if greedy_results and greedy_results[0].schedule is not None and trusted_greedy.schedule:
        g = greedy_results[0]
        assert g.schedule is not None
        out.append(
            _f(
                "opt.greedy_matches_rerun",
                set(g.schedule.selected_opportunity_ids)
                == set(trusted_greedy.schedule.selected_opportunity_ids)
                and g.feasible == trusted_greedy.feasible,
                "greedy schedule + feasibility match a deterministic server rerun",
                category=CheckCategory.MATHEMATICS,
                severity=Severity.CRITICAL,
            )
        )
    return out


def _verify_ownership(run: BenchmarkRun, problem: SchedulingProblem) -> list[VerificationFinding]:
    """Cross-benchmark / cross-problem ownership (third review, High #2).

    Every result must carry this benchmark's id + problem id, and the comparison's association
    ids must resolve to the benchmark's own exact/greedy/quantum records of the correct kind.
    Checksum equality alone is NOT accepted as problem identity — the internal problem id must
    match too, so two different problems with an identical checksum are rejected.
    """
    out: list[VerificationFinding] = []
    bid = run.id
    pid = run.problem_id
    children: list[object] = [*run.solver_results]
    if run.quantum_experiment is not None:
        children.append(run.quantum_experiment)
    if run.comparison is not None:
        children.append(run.comparison)
    same_owner = pid == problem.id and all(
        getattr(c, "benchmark_id", None) == bid and getattr(c, "problem_id", None) == pid
        for c in children
    )
    out.append(
        _f(
            "opt.ownership_anchors",
            same_owner,
            "every result carries this benchmark's id + internal problem id (not checksum alone)",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
            values={"benchmark_id": bid, "problem_id": pid},
        )
    )
    c = run.comparison
    if c is not None:
        by_id = {r.id: r for r in run.solver_results}
        exact = by_id.get(c.exact_result_id or "")
        greedy = by_id.get(c.greedy_result_id or "")
        exact_ok = (
            exact is not None
            and exact.solver_kind == SolverKind.EXACT
            and exact.benchmark_id == bid
        )
        greedy_ok = (
            greedy is not None
            and greedy.solver_kind == SolverKind.GREEDY
            and greedy.benchmark_id == bid
        )
        q = run.quantum_experiment
        quantum_ok = (c.quantum_experiment_id is None and q is None) or (
            q is not None and c.quantum_experiment_id == q.id and q.benchmark_id == bid
        )
        out.append(
            _f(
                "opt.comparison_associations_resolve",
                exact_ok and greedy_ok and quantum_ok,
                "comparison association ids resolve to this benchmark's exact/greedy/quantum "
                "records of the correct solver kind",
                category=CheckCategory.STRUCTURE,
                severity=Severity.CRITICAL,
                values={
                    "exact_ok": exact_ok,
                    "greedy_ok": greedy_ok,
                    "quantum_ok": quantum_ok,
                },
            )
        )
    return out


def _verify_comparison(
    run: BenchmarkRun, trusted_exact: SolverResult, trusted_greedy: SolverResult
) -> list[VerificationFinding]:
    out: list[VerificationFinding] = []
    if run.comparison is None:
        return out
    c = run.comparison
    # Authenticate the comparison policy against the SERVER registry; never trust the persisted
    # thresholds as proof of themselves (review finding #9). The conclusion is then re-derived
    # using the authoritative server thresholds, so coherently changing both a persisted
    # threshold and the conclusion is rejected.
    authoritative, policy_ok, policy_msg = authenticate_policy(
        policy_id=c.policy_id,
        policy_version=c.policy_version,
        policy_checksum_value=c.policy_checksum,
        thresholds=c.thresholds,
    )
    out.append(
        _f(
            "opt.policy_authenticated",
            policy_ok,
            f"comparison policy authenticated against the server registry ({policy_msg})",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"policy_id": c.policy_id, "policy_version": c.policy_version},
        )
    )
    server_thresholds = (authoritative or default_policy()).thresholds()
    expected, _rationale = conclude(
        exact_result=trusted_exact,
        greedy_result=trusted_greedy,
        quantum_experiment=run.quantum_experiment,
        thresholds=server_thresholds,
    )
    out.append(
        _f(
            "opt.conclusion_policy",
            c.conclusion == expected,
            "conclusion re-derived from the trusted re-solve + SERVER thresholds matches report",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"reported": c.conclusion.value, "expected": expected.value},
        )
    )
    # Comparison objective fields must equal the recomputed trusted values.
    opt_value, _sel = proven_optimum(trusted_exact)
    fields_ok = (
        run.comparison.known_optimum is None
        or abs(run.comparison.known_optimum - _num(opt_value)) < _TOL
    ) and (
        run.comparison.exact_objective is None
        or abs(run.comparison.exact_objective - _num(trusted_exact.objective_value)) < _TOL
    )
    out.append(
        _f(
            "opt.comparison_fields",
            fields_ok,
            "comparison objective fields match the independently recomputed values",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
        )
    )
    out.append(
        _f(
            "opt.comparison_bounded",
            run.comparison.epistemic_status.value in _BOUNDED_EPISTEMIC
            and bool(run.comparison.limitations.strip()),
            "comparison carries a bounded epistemic status + non-empty limitations",
            category=CheckCategory.POLICY,
        )
    )
    return out


# Scientifically misleading CLAIMS that must never appear in an artifact sidecar (review #16).
# These are affirmative overclaims; a negated mention ("NOT evidence of quantum advantage") is
# legitimate and must not match, so the phrases are specific.
_FORBIDDEN_PHRASES = (
    "quantum advantage verified",
    "quantum advantage demonstrated",
    "proven quantum advantage",
    "achieves quantum advantage",
    "quantum superiority",
    "production-ready quantum",
    "faster than classical",
    "outperforms classical",
)


def _contained(root: Path, rel: str) -> Path | None:
    """Resolve ``root/rel`` and require it to stay within ``root`` (rejects ../, abs, symlink)."""
    try:
        return ensure_within(root, root / rel)
    except Exception:
        return None


def _verify_artifacts(
    run: BenchmarkRun, artifacts_root: Path, problem_checksum_value: str
) -> list[VerificationFinding]:
    out: list[VerificationFinding] = []
    for art in run.artifacts:
        rel = art.get("path", "")
        # Derive the EXPECTED sidecar path from the artifact record + convention; never trust a
        # persisted sidecar path (review finding #15).
        expected_sidecar_rel = f"{rel}.json"
        target = _contained(artifacts_root, rel)
        sidecar_target = _contained(artifacts_root, expected_sidecar_rel)
        # The persisted sidecar_path (if any) must match the derived one exactly.
        sidecar_name_ok = art.get("sidecar_path", expected_sidecar_rel) == expected_sidecar_rel
        exists = target is not None and target.is_file()
        out.append(
            _f(
                f"opt.artifact_containment[{rel}]",
                target is not None and sidecar_target is not None and sidecar_name_ok and exists,
                "artifact + derived sidecar paths are contained in the root, named by convention",
                category=CheckCategory.PROVENANCE,
                severity=Severity.CRITICAL,
            )
        )
        if not exists or target is None or sidecar_target is None:
            continue
        actual = sha256_file(target)
        out.append(
            _f(
                f"opt.artifact_checksum[{rel}]",
                actual == art.get("checksum"),
                "artifact file checksum recomputed from disk matches the recorded checksum",
                category=CheckCategory.PROVENANCE,
                severity=Severity.CRITICAL,
                values={"actual": actual, "recorded": art.get("checksum")},
            )
        )
        meta_ok = False
        no_forbidden = True
        if sidecar_target.is_file():
            try:
                raw = sidecar_target.read_text("utf-8")
                meta = json.loads(raw)
                meta_ok = (
                    meta.get("checksum") == actual
                    and meta.get("problem_checksum") == problem_checksum_value
                    and meta.get("artifact_type") == art.get("type")
                    and str(meta.get("epistemic_status")) in _BOUNDED_EPISTEMIC
                    and bool(str(meta.get("limitations", "")).strip())
                    and "software_versions" in meta
                    and "seed" in meta
                )
                low = raw.lower()
                no_forbidden = not any(p in low for p in _FORBIDDEN_PHRASES)
            except Exception:
                meta_ok = False
        out.append(
            _f(
                f"opt.artifact_sidecar[{rel}]",
                meta_ok,
                "sidecar independently matches type/checksum/problem + carries bounded metadata",
                category=CheckCategory.PROVENANCE,
                severity=Severity.CRITICAL,
            )
        )
        out.append(
            _f(
                f"opt.artifact_no_overclaim[{rel}]",
                no_forbidden,
                "sidecar contains no scientifically misleading quantum-advantage language",
                category=CheckCategory.POLICY,
                severity=Severity.CRITICAL,
            )
        )
    return out


def all_critical_passed(findings: list[VerificationFinding]) -> bool:
    return not any(
        f.status == FindingStatus.FAILED and f.severity in (Severity.CRITICAL, Severity.ERROR)
        for f in findings
    )


def benchmark_verified_for_evidence(findings: list[VerificationFinding]) -> bool:
    """Authoritative evidence-release gate (review finding #5).

    True only when no CRITICAL/ERROR finding failed across ALL categories — problem checksum,
    classical baseline cardinality/authentication, quantum evidence + samples, comparison
    policy authentication, and artifacts/sidecars. When false the benchmark must not retain a
    positive conclusion, must not be marked verified, and must not create scientific-memory
    edges or be persisted as accepted evidence.
    """
    return all_critical_passed(findings)
