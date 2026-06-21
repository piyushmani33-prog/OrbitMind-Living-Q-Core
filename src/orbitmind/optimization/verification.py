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
from orbitmind.optimization.models import (
    BenchmarkRun,
    BenchmarkThresholds,
    PenaltyProofStatus,
    QuantumExperiment,
    SchedulingProblem,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.penalties import penalty_policy
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
    from orbitmind.optimization.models import ExperimentStatus

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

    # Per-sample independent re-evaluation + binary/width validity.
    sample_ok = True
    prob_ok = True
    total = 0
    feasible_shots = 0
    recomputed_best_feasible = None
    recomputed_best_infeasible = None
    seen_bitstrings: set[str] = set()
    for s in qexp.samples:
        total += s.count
        seen_bitstrings.add(s.bitstring)
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
            "opt.quantum_shot_total",
            total == qexp.total_shots,
            "sum of sample counts equals total_shots",
            category=CheckCategory.STRUCTURE,
            severity=Severity.CRITICAL,
            values={"sum": total, "reported": qexp.total_shots},
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
            evaluator.evaluate_bitstring(s.bitstring).selected_opportunity_ids == opt_bits
            and s.feasible
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


def _verify_comparison(
    run: BenchmarkRun, trusted_exact: SolverResult, trusted_greedy: SolverResult
) -> list[VerificationFinding]:
    out: list[VerificationFinding] = []
    if run.comparison is None:
        return out
    thresholds = run.comparison.thresholds or BenchmarkThresholds()
    expected, _rationale = conclude(
        exact_result=trusted_exact,
        greedy_result=trusted_greedy,
        quantum_experiment=run.quantum_experiment,
        thresholds=thresholds,
    )
    out.append(
        _f(
            "opt.conclusion_policy",
            run.comparison.conclusion == expected,
            "conclusion re-derived from the trusted re-solve + observed samples matches the report",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"reported": run.comparison.conclusion.value, "expected": expected.value},
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


def _verify_artifacts(
    run: BenchmarkRun, artifacts_root: Path, problem_checksum_value: str
) -> list[VerificationFinding]:
    out: list[VerificationFinding] = []
    for art in run.artifacts:
        rel = art.get("path", "")
        contained = True
        try:
            target = ensure_within(artifacts_root, artifacts_root / rel)
        except Exception:
            contained = False
            target = artifacts_root / rel
        exists = contained and target.is_file()
        out.append(
            _f(
                f"opt.artifact_containment[{rel}]",
                contained and exists,
                "artifact path is contained in the artifacts root and the file exists",
                category=CheckCategory.PROVENANCE,
                severity=Severity.CRITICAL,
            )
        )
        if not exists:
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
        sidecar = artifacts_root / art.get("sidecar_path", "")
        side_ok = False
        meta_ok = False
        if sidecar.is_file():
            try:
                meta = json.loads(sidecar.read_text("utf-8"))
                side_ok = meta.get("checksum") == actual
                meta_ok = (
                    meta.get("problem_checksum") == problem_checksum_value
                    and str(meta.get("epistemic_status")) in _BOUNDED_EPISTEMIC
                    and bool(str(meta.get("limitations", "")).strip())
                    and "software_versions" in meta
                    and "seed" in meta
                )
            except Exception:
                side_ok = False
        out.append(
            _f(
                f"opt.artifact_sidecar[{rel}]",
                side_ok and meta_ok,
                "sidecar checksum matches the file and required bounded metadata is present",
                category=CheckCategory.PROVENANCE,
                severity=Severity.CRITICAL,
            )
        )
    return out


def all_critical_passed(findings: list[VerificationFinding]) -> bool:
    return not any(
        f.status == FindingStatus.FAILED and f.severity in (Severity.CRITICAL, Severity.ERROR)
        for f in findings
    )
