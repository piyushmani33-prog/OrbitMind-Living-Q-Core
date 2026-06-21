"""Fair benchmark orchestration + the deterministic comparison-conclusion policy.

Classical and quantum solvers run on the SAME normalized problem. The conclusion is
policy-driven and never asserts general quantum advantage: ``quantum-competitive`` means
only that a feasible quantum result met a defined bounded threshold for this instance.
"""

from __future__ import annotations

import math

from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    BenchmarkComparison,
    BenchmarkRun,
    BenchmarkThresholds,
    ComparisonConclusion,
    ExperimentStatus,
    OptimalityStatus,
    QuantumExperiment,
    SchedulingProblem,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.policy import ComparisonPolicy, default_policy
from orbitmind.optimization.quantum import run_quantum_experiment
from orbitmind.optimization.solvers import solve_exact, solve_greedy
from orbitmind.quantum.adapter import quantum_available


def _classical_objective(result: SolverResult | None) -> float | None:
    """A classical result contributes an objective ONLY when it is a completed, feasible run of
    an expected solver kind with a finite objective (third review, Medium #4). Failed,
    timed-out, cancelled, unsupported, pending, running, or inconclusive results — even if they
    retained a stale ``feasible``/``objective_value`` — contribute nothing.
    """
    if (
        result is None
        or result.status != ExperimentStatus.COMPLETED
        or result.solver_kind not in (SolverKind.EXACT, SolverKind.GREEDY)
        or not result.feasible
        or result.objective_value is None
        or not math.isfinite(result.objective_value)
    ):
        return None
    return result.objective_value


def proven_optimum(
    exact: SolverResult | None,
) -> tuple[float | None, tuple[str, ...] | None]:
    """Return (optimum, selection) ONLY for a completed, proven-optimal, feasible exact run.

    A merely feasible / timed-out / unsupported / failed exact result is NOT a known
    optimum (review finding #10).
    """
    if (
        exact is not None
        and exact.status == ExperimentStatus.COMPLETED
        and exact.optimality_status == OptimalityStatus.OPTIMAL
        and exact.feasible
        and exact.objective_value is not None
        and exact.schedule is not None
    ):
        return exact.objective_value, exact.schedule.selected_opportunity_ids
    return None, None


def conclude(
    *,
    exact_result: SolverResult | None,
    greedy_result: SolverResult | None,
    quantum_experiment: QuantumExperiment | None,
    thresholds: BenchmarkThresholds,
) -> tuple[ComparisonConclusion, str]:
    """Deterministic comparison policy. Pure function over solver/experiment records."""
    exact_obj = _classical_objective(exact_result)
    greedy_obj = _classical_objective(greedy_result)
    known_optimum, _selection = proven_optimum(exact_result)
    best_classical = max([o for o in (exact_obj, greedy_obj) if o is not None], default=None)

    # ---- STATUS GUARDS FIRST (review finding #19): a non-completed / unverifiable
    # quantum run can NEVER receive a positive conclusion, regardless of any objective. ----
    def _classical_fallback() -> tuple[ComparisonConclusion, str]:
        if known_optimum is not None:
            return ComparisonConclusion.CLASSICAL_EXACT_BEST, "exact optimum; no quantum comparison"
        if greedy_obj is not None:
            return (
                ComparisonConclusion.CLASSICAL_GREEDY_BEST,
                "greedy feasible; no quantum comparison",
            )
        return ComparisonConclusion.INSUFFICIENT_EVIDENCE, "no feasible classical solution"

    if quantum_experiment is None or quantum_experiment.status == ExperimentStatus.UNSUPPORTED:
        return _classical_fallback()
    if quantum_experiment.status == ExperimentStatus.FAILED:
        return ComparisonConclusion.EXPERIMENT_FAILED, f"quantum failed: {quantum_experiment.error}"
    if quantum_experiment.status in (
        ExperimentStatus.TIMED_OUT,
        ExperimentStatus.CANCELLED,
        ExperimentStatus.PENDING,
        ExperimentStatus.RUNNING,
        ExperimentStatus.INCONCLUSIVE,
    ):
        return (
            ComparisonConclusion.INSUFFICIENT_EVIDENCE,
            f"quantum status '{quantum_experiment.status.value}' is non-positive by policy",
        )
    if quantum_experiment.status != ExperimentStatus.COMPLETED:
        return ComparisonConclusion.INSUFFICIENT_EVIDENCE, "quantum run did not complete"
    # The quantum experiment must be the SAME instance as the classical baselines.
    if (
        exact_result is not None
        and quantum_experiment.problem_checksum != exact_result.problem_checksum
    ):
        return (
            ComparisonConclusion.INSUFFICIENT_EVIDENCE,
            "quantum experiment ran a different problem checksum",
        )

    best_feasible = quantum_experiment.best_feasible_sample
    if best_feasible is None:
        return ComparisonConclusion.QUANTUM_INFEASIBLE, "no feasible quantum sample observed"

    qobj = best_feasible.objective_value
    if quantum_experiment.feasible_sample_ratio < thresholds.min_feasible_sample_ratio:
        return (
            ComparisonConclusion.INSUFFICIENT_EVIDENCE,
            f"feasible-sample ratio {quantum_experiment.feasible_sample_ratio:.3f} below "
            f"threshold {thresholds.min_feasible_sample_ratio}",
        )

    reference = known_optimum if known_optimum is not None else best_classical
    if reference is None:
        return ComparisonConclusion.INSUFFICIENT_EVIDENCE, "no classical reference objective"
    gap_rel = (reference - qobj) / reference if reference > 0 else (reference - qobj)

    if known_optimum is not None:
        # Compared against a PROVEN optimum.
        if gap_rel <= thresholds.competitive_relative_gap:
            return (
                ComparisonConclusion.QUANTUM_COMPETITIVE,
                f"quantum feasible obj={qobj} within rel-gap {gap_rel:.4f} of the proven optimum "
                f"{reference} (threshold {thresholds.competitive_relative_gap}); bounded-instance "
                "threshold met, NOT a claim of quantum advantage",
            )
        return (
            ComparisonConclusion.QUANTUM_WORSE,
            f"quantum obj={qobj} below the proven optimum {reference} (rel-gap {gap_rel:.4f})",
        )
    # Optimum NOT proven (exact unavailable/timed out): compare to the best classical heuristic.
    if best_classical is not None and qobj == best_classical:
        return (
            ComparisonConclusion.EQUIVALENT_OBJECTIVE,
            f"quantum ties the best classical obj={qobj}; optimum not proven for this instance",
        )
    if best_classical is not None and qobj > best_classical:
        return (
            ComparisonConclusion.QUANTUM_COMPETITIVE,
            f"quantum obj={qobj} exceeds the best classical heuristic {best_classical} on this "
            "bounded instance (optimum not proven; NOT a claim of quantum advantage)",
        )
    return (
        ComparisonConclusion.QUANTUM_WORSE,
        f"quantum obj={qobj} below the best classical {best_classical}",
    )


def run_benchmark(
    problem: SchedulingProblem,
    *,
    seed: int = 1,
    shots: int = 2048,
    optimizer_iterations: int = 24,
    qaoa_layers: int = 1,
    timeout_seconds: float = 30.0,
    policy: ComparisonPolicy | None = None,
    run_quantum: bool = True,
) -> BenchmarkRun:
    """Run exact + greedy + (optional) quantum on the same normalized problem instance.

    The comparison thresholds come from the SERVER-owned ``policy`` (review finding #9), never
    from client input trusted at verification time.
    """
    policy = policy or default_policy()
    thresholds = policy.thresholds()
    evaluator = Evaluator(problem)

    exact = solve_exact(
        problem,
        SolverConfiguration(
            solver_kind=SolverKind.EXACT, seed=seed, timeout_seconds=timeout_seconds
        ),
        evaluator,
    )
    greedy = solve_greedy(
        problem,
        SolverConfiguration(
            solver_kind=SolverKind.GREEDY, seed=seed, timeout_seconds=timeout_seconds
        ),
        evaluator,
    )
    known_optimum, optimum_selection = proven_optimum(exact)

    quantum: QuantumExperiment | None = None
    if run_quantum:
        config = SolverConfiguration(
            solver_kind=SolverKind.QUANTUM_QAOA,
            seed=seed,
            timeout_seconds=timeout_seconds,
            shots=shots,
            optimizer_iterations=optimizer_iterations,
            qaoa_layers=qaoa_layers,
        )
        if quantum_available():
            quantum = run_quantum_experiment(
                problem,
                config,
                evaluator,
                known_optimum=known_optimum,
                optimum_selection=optimum_selection,
            )
        else:
            quantum = QuantumExperiment(
                problem_checksum=problem.checksum,
                status=ExperimentStatus.UNSUPPORTED,
                configuration=config,
                seed=seed,
                error="Aer/Qiskit not installed",
            )

    conclusion, rationale = conclude(
        exact_result=exact,
        greedy_result=greedy,
        quantum_experiment=quantum,
        thresholds=thresholds,
    )
    quantum_objective = (
        quantum.best_feasible_sample.objective_value
        if quantum is not None and quantum.best_feasible_sample is not None
        else None
    )
    objective_gap = (
        known_optimum - quantum_objective
        if known_optimum is not None and quantum_objective is not None
        else None
    )
    comparison = BenchmarkComparison(
        problem_checksum=problem.checksum,
        exact_result_id=exact.id,
        greedy_result_id=greedy.id,
        quantum_experiment_id=quantum.id if quantum is not None else None,
        exact_objective=_classical_objective(exact),
        greedy_objective=_classical_objective(greedy),
        quantum_objective=quantum_objective,
        known_optimum=known_optimum,
        objective_gap=objective_gap,
        conclusion=conclusion,
        thresholds=thresholds,
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_checksum=policy.checksum,
        rationale=rationale,
    )
    return BenchmarkRun(
        problem_checksum=problem.checksum,
        solver_results=[exact, greedy],
        quantum_experiment=quantum,
        comparison=comparison,
    )
