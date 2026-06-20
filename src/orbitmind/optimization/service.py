"""Optimization service facade: session + audit + verification + persistence + memory.

Coordinates the deterministic core (problem/solvers/qubo/benchmark/verification) with
persistence, bounded artifacts, and bounded scientific-memory entity links. An
experimental quantum result never directly controls a production mission; it is recorded,
verified, and compared only.
"""

from __future__ import annotations

from orbitmind.core.config import Settings
from orbitmind.core.errors import NotFoundError
from orbitmind.core.logging import get_logger
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.memory.models import (
    EntityKind,
    EntityReference,
    GraphEdge,
    GraphEdgeKind,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    BenchmarkRun,
    BenchmarkThresholds,
    ExperimentStatus,
    QuantumExperiment,
    SchedulingProblem,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.quantum import run_quantum_experiment
from orbitmind.optimization.solvers import solve_exact, solve_greedy
from orbitmind.optimization.verification import all_critical_passed, verify_benchmark
from orbitmind.persistence.database import Database
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.quantum.adapter import quantum_available
from orbitmind.verification.models import VerificationFinding

_log = get_logger("optimization.service")


class OptimizationService:
    def __init__(self, *, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._db = database
        from orbitmind.visualization.optimization_charts import OptimizationVisualizationService

        self._viz = OptimizationVisualizationService(settings.resolved_artifacts_dir())

    # ---- problems ----------------------------------------------------------
    def create_problem(self, problem: SchedulingProblem) -> SchedulingProblem:
        normalized = normalize_problem(problem)
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyOptimizationRepository(session)
            repo.save_problem(normalized)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.OPTIMIZATION_PROBLEM_CREATED,
                    detail={
                        "checksum": normalized.checksum,
                        "num_vars": len(normalized.opportunities),
                    },
                )
            )
            session.commit()
        return normalized

    def get_problem(self, problem_id: str) -> SchedulingProblem | None:
        with self._db.session() as session:
            return SqlAlchemyOptimizationRepository(session).get_problem(problem_id)

    def list_problems(self, limit: int, offset: int) -> tuple[int, list[SchedulingProblem]]:
        with self._db.session() as session:
            repo = SqlAlchemyOptimizationRepository(session)
            return repo.count_problems(), repo.list_problems(limit, offset)

    def _require_problem(self, problem_id: str) -> SchedulingProblem:
        problem = self.get_problem(problem_id)
        if problem is None:
            raise NotFoundError("optimization problem not found")
        return problem

    # ---- standalone solves -------------------------------------------------
    def solve_classical(
        self, problem_id: str, *, solver_kind: SolverKind, seed: int, timeout_seconds: float
    ) -> SolverResult:
        problem = self._require_problem(problem_id)
        evaluator = Evaluator(problem)
        config = SolverConfiguration(
            solver_kind=solver_kind, seed=seed, timeout_seconds=timeout_seconds
        )
        if solver_kind == SolverKind.EXACT:
            result = solve_exact(problem, config, evaluator)
        elif solver_kind == SolverKind.GREEDY:
            result = solve_greedy(problem, config, evaluator)
        else:
            raise NotFoundError(f"unsupported classical solver: {solver_kind}")
        # Independent re-verification of the reported objective/feasibility.
        if result.schedule is not None:
            recheck = evaluator.evaluate(set(result.schedule.selected_opportunity_ids))
            if recheck.objective_value != (result.objective_value or recheck.objective_value):
                result = result.model_copy(update={"status": ExperimentStatus.FAILED})
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyOptimizationRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.CLASSICAL_SOLVE_REQUESTED, detail={"kind": solver_kind.value}
                )
            )
            repo.save_solver_result(result, benchmark_id=None, problem_id=problem.id)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.CLASSICAL_SOLVE_COMPLETED,
                    detail={
                        "kind": solver_kind.value,
                        "objective": result.objective_value,
                        "feasible": result.feasible,
                        "status": result.status.value,
                    },
                )
            )
            session.commit()
        return result

    def solve_quantum(
        self,
        problem_id: str,
        *,
        seed: int,
        shots: int,
        optimizer_iterations: int,
        qaoa_layers: int,
        timeout_seconds: float,
    ) -> QuantumExperiment:
        problem = self._require_problem(problem_id)
        config = SolverConfiguration(
            solver_kind=SolverKind.QUANTUM_QAOA,
            seed=seed,
            timeout_seconds=timeout_seconds,
            shots=shots,
            optimizer_iterations=optimizer_iterations,
            qaoa_layers=qaoa_layers,
        )
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyOptimizationRepository(session)
            audit.add_audit_event(AuditEvent(action=AuditAction.QUANTUM_EXPERIMENT_REQUESTED))
            if not quantum_available():
                experiment = QuantumExperiment(
                    problem_checksum=problem.checksum,
                    status=ExperimentStatus.UNSUPPORTED,
                    configuration=config,
                    seed=seed,
                    error="Aer/Qiskit not installed",
                )
                audit.add_audit_event(AuditEvent(action=AuditAction.QUANTUM_UNSUPPORTED))
            else:
                evaluator = Evaluator(problem)
                exact = solve_exact(
                    problem,
                    SolverConfiguration(
                        solver_kind=SolverKind.EXACT, seed=seed, timeout_seconds=timeout_seconds
                    ),
                    evaluator,
                )
                experiment = run_quantum_experiment(
                    problem,
                    config,
                    evaluator,
                    known_optimum=exact.objective_value if exact.feasible else None,
                    optimum_selection=exact.schedule.selected_opportunity_ids
                    if exact.schedule
                    else None,
                )
                audit.add_audit_event(
                    AuditEvent(
                        action=AuditAction.QUANTUM_EXPERIMENT_COMPLETED,
                        detail={
                            "status": experiment.status.value,
                            "feasible_ratio": experiment.feasible_sample_ratio,
                        },
                    )
                )
            repo.save_quantum_experiment(experiment, benchmark_id=None)
            session.commit()
        return experiment

    # ---- full benchmark ----------------------------------------------------
    def benchmark(
        self,
        problem_id: str,
        *,
        seed: int = 1,
        shots: int = 2048,
        optimizer_iterations: int = 24,
        qaoa_layers: int = 1,
        timeout_seconds: float = 30.0,
        run_quantum: bool = True,
        generate_artifacts: bool = False,
        thresholds: BenchmarkThresholds | None = None,
    ) -> tuple[BenchmarkRun, list[VerificationFinding]]:
        problem = self._require_problem(problem_id)
        run = run_benchmark(
            problem,
            seed=seed,
            shots=shots,
            optimizer_iterations=optimizer_iterations,
            qaoa_layers=qaoa_layers,
            timeout_seconds=timeout_seconds,
            thresholds=thresholds,
            run_quantum=run_quantum,
        )
        findings = verify_benchmark(problem, run)
        verified = all_critical_passed(findings)
        if generate_artifacts:
            artifacts = self._viz.generate(problem, run, findings, seed=seed)
            run = run.model_copy(update={"artifacts": artifacts})

        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyOptimizationRepository(session)
            memory = SqlAlchemyMemoryRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.BENCHMARK_REQUESTED, detail={"problem": problem.checksum}
                )
            )
            repo.save_benchmark(run, problem_id=problem.id, verification_passed=verified)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.OPTIMIZATION_VERIFIED
                    if verified
                    else AuditAction.OPTIMIZATION_VERIFICATION_FAILED,
                    detail={
                        "checks": len(findings),
                        "failed": sum(1 for f in findings if not f.passed),
                    },
                )
            )
            for art in run.artifacts:
                audit.add_audit_event(
                    AuditEvent(
                        action=AuditAction.OPTIMIZATION_ARTIFACT_GENERATED,
                        detail={"type": art["type"]},
                    )
                )
            if verified:
                self._register_memory_links(memory, problem, run)
                audit.add_audit_event(AuditEvent(action=AuditAction.BENCHMARK_MEMORY_REGISTERED))
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.BENCHMARK_COMPLETED,
                    detail={
                        "conclusion": run.comparison.conclusion.value
                        if run.comparison
                        else "unknown",
                        "verified": verified,
                    },
                )
            )
            session.commit()
        _log.info(
            "optimization.benchmark",
            conclusion=run.comparison.conclusion.value if run.comparison else "unknown",
            verified=verified,
        )
        return run, findings

    def _register_memory_links(
        self, memory: SqlAlchemyMemoryRepository, problem: SchedulingProblem, run: BenchmarkRun
    ) -> None:
        """Bounded, specific entity links only — NO broad scientific claims (section 16)."""
        problem_ref = EntityReference(kind=EntityKind.OPTIMIZATION_PROBLEM, entity_id=problem.id)
        exact_id = None
        for result in run.solver_results:
            run_ref = EntityReference(kind=EntityKind.SOLVER_RUN, entity_id=result.id)
            memory.add_graph_edge(
                GraphEdge(
                    from_ref=problem_ref,
                    edge_kind=GraphEdgeKind.SOLVED_BY,
                    to_ref=run_ref,
                    source="phase4a-benchmark",
                )
            )
            if result.schedule is not None:
                memory.add_graph_edge(
                    GraphEdge(
                        from_ref=run_ref,
                        edge_kind=GraphEdgeKind.PRODUCED,
                        to_ref=EntityReference(kind=EntityKind.SCHEDULE, entity_id=result.id),
                        source="phase4a-benchmark",
                    )
                )
            if result.solver_kind == SolverKind.EXACT:
                exact_id = result.id
        if run.quantum_experiment is not None and exact_id is not None:
            memory.add_graph_edge(
                GraphEdge(
                    from_ref=EntityReference(
                        kind=EntityKind.QUANTUM_EXPERIMENT, entity_id=run.quantum_experiment.id
                    ),
                    edge_kind=GraphEdgeKind.COMPARED_AGAINST,
                    to_ref=EntityReference(kind=EntityKind.SOLVER_RUN, entity_id=exact_id),
                    source="phase4a-benchmark",
                )
            )
        if run.comparison is not None:
            comp_ref = EntityReference(
                kind=EntityKind.BENCHMARK_COMPARISON, entity_id=run.comparison.id
            )
            for art in run.artifacts:
                memory.add_graph_edge(
                    GraphEdge(
                        from_ref=comp_ref,
                        edge_kind=GraphEdgeKind.SUPPORTED_BY,
                        to_ref=EntityReference(
                            kind=EntityKind.OPTIMIZATION_ARTIFACT, entity_id=art["checksum"]
                        ),
                        source="phase4a-benchmark",
                    )
                )

    # ---- reads -------------------------------------------------------------
    def get_run(self, run_id: str) -> SolverResult | QuantumExperiment | None:
        with self._db.session() as session:
            return SqlAlchemyOptimizationRepository(session).get_solver_run(run_id)

    def list_runs(self, limit: int, offset: int) -> list[dict[str, object]]:
        with self._db.session() as session:
            return SqlAlchemyOptimizationRepository(session).list_runs(limit, offset)

    def get_artifacts(self, scope_id: str) -> list[dict[str, str]]:
        with self._db.session() as session:
            rows = SqlAlchemyOptimizationRepository(session).get_artifacts(scope_id)
            return [
                {
                    "type": r.artifact_type,
                    "path": r.path,
                    "sidecar_path": r.sidecar_path,
                    "checksum": r.checksum,
                }
                for r in rows
            ]
