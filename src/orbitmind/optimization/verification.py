"""Deterministic verification of benchmark results (independent of the solvers).

Re-derives everything from the problem (the source of truth) and checks the reported
results. A result failing a CRITICAL/ERROR check must not be treated as successful.
"""

from __future__ import annotations

from itertools import product
from typing import Any

from orbitmind.optimization.benchmark import conclude
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    BenchmarkRun,
    BenchmarkThresholds,
    SchedulingProblem,
    SolverKind,
)
from orbitmind.optimization.problem import problem_checksum, variable_order
from orbitmind.optimization.qubo import build_qubo, qubo_energy
from orbitmind.verification.models import (
    CheckCategory,
    FindingStatus,
    Severity,
    VerificationFinding,
)

_EXHAUSTIVE_MAX_VARS = 16


def _finding(
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


def verify_benchmark(problem: SchedulingProblem, run: BenchmarkRun) -> list[VerificationFinding]:
    """Independently verify a benchmark run. Returns findings (empty failures == clean)."""
    findings: list[VerificationFinding] = []
    evaluator = Evaluator(problem)
    order = variable_order(problem)
    valid_ids = set(order)

    # Problem checksum integrity + same-instance comparison.
    recomputed = problem_checksum(problem)
    findings.append(
        _finding(
            "opt.problem_checksum",
            recomputed == problem.checksum,
            "problem checksum matches recomputed canonical content",
            category=CheckCategory.PROVENANCE,
            severity=Severity.CRITICAL,
            values={"stored": problem.checksum, "recomputed": recomputed},
        )
    )
    instance_checksums = {problem.checksum, run.problem_checksum}
    for result in run.solver_results:
        instance_checksums.add(result.problem_checksum)
    if run.quantum_experiment is not None:
        instance_checksums.add(run.quantum_experiment.problem_checksum)
    findings.append(
        _finding(
            "opt.same_instance",
            len(instance_checksums) == 1,
            "every solver and the quantum experiment ran the SAME problem instance",
            category=CheckCategory.POLICY,
            severity=Severity.CRITICAL,
            values={"checksums": sorted(instance_checksums)},
        )
    )

    # QUBO ↔ evaluator equivalence (exhaustive for tiny instances).
    qubo = build_qubo(problem)
    findings.append(
        _finding(
            "opt.qubo_variable_order",
            qubo.variable_opportunities == order,
            "QUBO variable ordering preserved (index 0 first)",
            category=CheckCategory.MATHEMATICS,
            severity=Severity.CRITICAL,
        )
    )
    if qubo.num_vars <= _EXHAUSTIVE_MAX_VARS:
        mism = 0
        for bits_t in product("01", repeat=qubo.num_vars):
            bits = "".join(bits_t)
            if (
                abs(
                    qubo_energy(qubo, bits) + evaluator.evaluate_bitstring(bits).penalized_objective
                )
                > 1e-9
            ):
                mism += 1
        findings.append(
            _finding(
                "opt.qubo_energy_equivalence",
                mism == 0,
                "QUBO energy == -penalized_objective for ALL bitstrings",
                category=CheckCategory.MATHEMATICS,
                severity=Severity.CRITICAL,
                values={"mismatches": mism, "num_vars": qubo.num_vars},
            )
        )

    # Each solver schedule: selected exist + independent re-evaluation matches.
    for result in run.solver_results:
        if result.schedule is None or result.evaluation is None:
            continue
        selected = set(result.schedule.selected_opportunity_ids)
        findings.append(
            _finding(
                f"opt.selected_exist.{result.solver_kind.value}",
                selected <= valid_ids,
                f"{result.solver_name}: all selected opportunities exist",
                category=CheckCategory.STRUCTURE,
            )
        )
        recomputed_eval = evaluator.evaluate(selected)
        findings.append(
            _finding(
                f"opt.objective_recompute.{result.solver_kind.value}",
                abs(recomputed_eval.objective_value - (result.objective_value or -1)) < 1e-9
                and recomputed_eval.feasible == result.feasible,
                f"{result.solver_name}: objective + feasibility re-verified independently",
                category=CheckCategory.MATHEMATICS,
                values={
                    "reported_objective": result.objective_value,
                    "recomputed_objective": recomputed_eval.objective_value,
                    "reported_feasible": result.feasible,
                    "recomputed_feasible": recomputed_eval.feasible,
                },
            )
        )
        if result.feasible:
            findings.append(
                _finding(
                    f"opt.feasible_no_violation.{result.solver_kind.value}",
                    len(recomputed_eval.violations) == 0,
                    f"{result.solver_name}: feasible schedule has zero violations "
                    "(overlaps, capacity, mandatory, per-target all satisfied)",
                    category=CheckCategory.POLICY,
                )
            )
        # Seed recorded.
        findings.append(
            _finding(
                f"opt.seed_recorded.{result.solver_kind.value}",
                isinstance(result.seed, int),
                f"{result.solver_name}: seed recorded ({result.seed})",
                category=CheckCategory.PROVENANCE,
                severity=Severity.WARNING,
            )
        )

    # Quantum-specific verification.
    qexp = run.quantum_experiment
    if qexp is not None and qexp.circuit_metadata is not None:
        findings.append(
            _finding(
                "opt.quantum_simulator_only",
                qexp.circuit_metadata.simulator_backend == "AerSimulator",
                "quantum experiment is simulator-only (Aer; no hardware)",
                category=CheckCategory.POLICY,
                severity=Severity.CRITICAL,
                values={"backend": qexp.circuit_metadata.simulator_backend},
            )
        )
        findings.append(
            _finding(
                "opt.quantum_seeds_recorded",
                isinstance(qexp.circuit_metadata.seed_simulator, int)
                and isinstance(qexp.circuit_metadata.seed_transpiler, int),
                "simulator + transpiler seeds recorded",
                category=CheckCategory.PROVENANCE,
            )
        )
        if qexp.best_feasible_sample is not None:
            observed = {s.bitstring for s in qexp.samples}
            findings.append(
                _finding(
                    "opt.quantum_sample_observed",
                    qexp.best_feasible_sample.bitstring in observed,
                    "selected quantum sample was actually observed in the shot results",
                    category=CheckCategory.STRUCTURE,
                    severity=Severity.CRITICAL,
                )
            )
            recomputed_q = evaluator.evaluate_bitstring(qexp.best_feasible_sample.bitstring)
            findings.append(
                _finding(
                    "opt.quantum_sample_reverified",
                    recomputed_q.feasible
                    and abs(
                        recomputed_q.objective_value - qexp.best_feasible_sample.objective_value
                    )
                    < 1e-9,
                    "selected quantum sample independently re-verified feasible + objective",
                    category=CheckCategory.MATHEMATICS,
                )
            )

    # Conclusion follows policy.
    thresholds = run.comparison.thresholds if run.comparison is not None else _default_thresholds()
    expected, _rationale = conclude(
        exact_result=next(
            (r for r in run.solver_results if r.solver_kind == SolverKind.EXACT), None
        ),
        greedy_result=next(
            (r for r in run.solver_results if r.solver_kind == SolverKind.GREEDY), None
        ),
        quantum_experiment=qexp,
        thresholds=thresholds,
    )
    if run.comparison is not None:
        findings.append(
            _finding(
                "opt.conclusion_policy",
                run.comparison.conclusion == expected,
                "benchmark conclusion follows the deterministic comparison policy",
                category=CheckCategory.POLICY,
                severity=Severity.CRITICAL,
                values={"reported": run.comparison.conclusion.value, "expected": expected.value},
            )
        )
    return findings


def _default_thresholds() -> BenchmarkThresholds:
    return BenchmarkThresholds()


def all_critical_passed(findings: list[VerificationFinding]) -> bool:
    return not any(
        f.status == FindingStatus.FAILED and f.severity in (Severity.CRITICAL, Severity.ERROR)
        for f in findings
    )
