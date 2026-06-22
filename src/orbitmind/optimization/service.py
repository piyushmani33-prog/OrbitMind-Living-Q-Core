"""Optimization service facade: session + audit + verification + persistence + memory.

Coordinates the deterministic core (problem/solvers/qubo/benchmark/verification) with
persistence, bounded artifacts, and bounded scientific-memory entity links. An
experimental quantum result never directly controls a production mission; it is recorded,
verified, and compared only.
"""

from __future__ import annotations

from orbitmind.core.config import Settings
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.logging import get_logger
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.memory.models import (
    EntityKind,
    EntityReference,
    GraphEdge,
    GraphEdgeKind,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.optimization.benchmark import proven_optimum, run_benchmark
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    BenchmarkRun,
    ComparisonConclusion,
    ExperimentStatus,
    QuantumExperiment,
    SchedulingProblem,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.policy import DEFAULT_POLICY_ID, get_policy
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.quantum import run_quantum_experiment
from orbitmind.optimization.receipts import (
    BenchmarkExecutionReceipt,
    EvidenceReceiptSigner,
    build_receipt,
    verify_receipt,
)
from orbitmind.optimization.solvers import solve_exact, solve_greedy
from orbitmind.optimization.verification import benchmark_verified_for_evidence, verify_benchmark
from orbitmind.persistence.database import Database
from orbitmind.persistence.optimization_repository import SqlAlchemyOptimizationRepository
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.quantum.adapter import quantum_available
from orbitmind.verification.models import (
    CheckCategory,
    FindingStatus,
    Severity,
    VerificationFinding,
)

_log = get_logger("optimization.service")


class OptimizationService:
    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        receipt_signer: EvidenceReceiptSigner | None = None,
        receipt_signers: dict[str, EvidenceReceiptSigner] | None = None,
    ) -> None:
        self._settings = settings
        self._db = database
        # Evidence-receipt signing (third review, High #1). ``receipt_signer`` signs new receipts
        # (None => provenance unavailable, evidence stays unaccepted); ``receipt_signers`` maps
        # key id -> signer for verification (incl. retired keys for historical receipts).
        self._receipt_signer = receipt_signer
        self._receipt_signers: dict[str, EvidenceReceiptSigner] = receipt_signers or (
            {receipt_signer.key_id: receipt_signer} if receipt_signer is not None else {}
        )
        from orbitmind.visualization.optimization_charts import OptimizationVisualizationService

        self._viz = OptimizationVisualizationService(settings.resolved_artifacts_dir())

    # ---- problems ----------------------------------------------------------
    def create_problem(self, problem: SchedulingProblem) -> SchedulingProblem:
        normalized = normalize_problem(problem)
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyOptimizationRepository(session)
            persisted_id = repo.save_problem(normalized)
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
        # Idempotent: if the same canonical problem already existed, return the PERSISTED
        # entity + its real id, not the freshly-generated (unpersisted) one (finding #9).
        if persisted_id != normalized.id:
            existing = self.get_problem(persisted_id)
            if existing is not None:
                return existing
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
                # A known optimum requires a COMPLETED, proven-optimal exact run (finding #10).
                known_optimum, optimum_selection = proven_optimum(exact)
                experiment = run_quantum_experiment(
                    problem,
                    config,
                    evaluator,
                    known_optimum=known_optimum,
                    optimum_selection=optimum_selection,
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
            repo.save_quantum_experiment(experiment, benchmark_id=None, problem_id=problem.id)
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
        policy_id: str = DEFAULT_POLICY_ID,
    ) -> tuple[BenchmarkRun, list[VerificationFinding]]:
        problem = self._require_problem(problem_id)
        policy = get_policy(policy_id)
        if policy is None:
            raise ValidationError(f"unknown comparison policy id '{policy_id}'")
        run = run_benchmark(
            problem,
            seed=seed,
            shots=shots,
            optimizer_iterations=optimizer_iterations,
            qaoa_layers=qaoa_layers,
            timeout_seconds=timeout_seconds,
            policy=policy,
            run_quantum=run_quantum,
        )
        artifacts_root = self._settings.resolved_artifacts_dir()
        stage = "verification"
        try:
            findings = verify_benchmark(problem, run)
            if generate_artifacts:
                stage = "artifact-generation"
                artifacts = self._viz.generate(problem, run, findings, seed=seed)
                run = run.model_copy(update={"artifacts": artifacts})
                stage = "artifact-verification"
                findings = verify_benchmark(problem, run, artifacts_root=artifacts_root)

            # Evidence-origin authentication (third review, High #1): a signed execution receipt,
            # modelled as a verification finding so it joins the release gate (no signer or a
            # failed receipt leaves the benchmark UNACCEPTED).
            receipt, receipt_finding = self._authorize_evidence(run, findings)
            findings = [*findings, receipt_finding]
            verified = benchmark_verified_for_evidence(findings)
            if not verified and run.comparison is not None:
                run = run.model_copy(
                    update={
                        "comparison": run.comparison.model_copy(
                            update={
                                "conclusion": ComparisonConclusion.INSUFFICIENT_EVIDENCE,
                                "rationale": "verification failed; conclusion downgraded: "
                                + run.comparison.rationale,
                            }
                        )
                    }
                )

            stage = "persistence"
            self._persist_benchmark(run, problem, findings, verified, receipt)
        except Exception as exc:
            # Idempotent cleanup of any staged/promoted artifacts + a durable failure audit in a
            # SEPARATE transaction (the main one rolled back) — review Medium #3.
            if generate_artifacts:
                self._viz.cleanup(run.id)
            self._record_failure_audit(stage=stage, benchmark_id=run.id, problem=problem, exc=exc)
            raise

        _log.info(
            "optimization.benchmark",
            conclusion=run.comparison.conclusion.value if run.comparison else "unknown",
            verified=verified,
        )
        return run, findings

    def _persist_benchmark(
        self,
        run: BenchmarkRun,
        problem: SchedulingProblem,
        findings: list[VerificationFinding],
        verified: bool,
        receipt: BenchmarkExecutionReceipt | None,
    ) -> None:
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
            if verified and receipt is not None:
                repo.save_receipt(receipt)
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

    def _record_failure_audit(
        self, *, stage: str, benchmark_id: str, problem: SchedulingProblem, exc: Exception
    ) -> None:
        """Persist a bounded failure audit in its own short transaction; log-only if the DB is
        unavailable. Contains NO secrets, signing key, or raw environment values (Medium #3)."""
        detail = {
            "operation": "benchmark",
            "benchmark_attempt_id": benchmark_id,
            "problem_id": problem.id,
            "problem_checksum": problem.checksum,
            "stage": stage,
            "exception_class": type(exc).__name__,
            "error_code": "benchmark_failed",
        }
        try:
            with self._db.session() as session:
                SqlAlchemyMissionRepository(session).add_audit_event(
                    AuditEvent(action=AuditAction.BENCHMARK_FAILED, detail=detail)
                )
                session.commit()
        except Exception:  # pragma: no cover - final fallback when the DB itself is unavailable
            _log.error("optimization.benchmark.failure", **detail)

    def _authorize_evidence(
        self, run: BenchmarkRun, findings: list[VerificationFinding]
    ) -> tuple[BenchmarkExecutionReceipt | None, VerificationFinding]:
        """Build + verify a signed execution receipt and express it as a release finding.

        When no signer is configured the evidence runs diagnostically but is never accepted
        (execution provenance unavailable); a failed receipt likewise blocks acceptance.
        """

        def finding(passed: bool, explanation: str) -> VerificationFinding:
            return VerificationFinding(
                check_id="opt.execution_receipt",
                severity=Severity.INFO if passed else Severity.CRITICAL,
                status=FindingStatus.PASSED if passed else FindingStatus.FAILED,
                explanation=explanation,
                category=CheckCategory.PROVENANCE,
            )

        # Only build a receipt over an otherwise-clean benchmark; a semantically invalid run is
        # already non-positive and must not be signed as accepted evidence.
        if not benchmark_verified_for_evidence(findings):
            return None, finding(False, "benchmark failed semantic verification; not signed")
        if self._receipt_signer is None:
            return None, finding(
                False, "execution provenance unavailable: no evidence signer configured"
            )
        receipt = build_receipt(run, signer=self._receipt_signer)
        result = verify_receipt(receipt, run=run, signers=self._receipt_signers)
        if not result.ok:
            return None, finding(False, f"execution receipt invalid: {', '.join(result.reasons)}")
        return receipt, finding(True, "execution receipt signed + verified by the trusted runtime")

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
        """Return safe, path-free artifact metadata (third review, Medium #2). Internal
        filesystem paths (path/sidecar_path/root/tmp) never leave the service."""
        media = {".png": "image/png", ".json": "application/json", ".txt": "text/plain"}
        with self._db.session() as session:
            rows = SqlAlchemyOptimizationRepository(session).get_artifacts(scope_id)
            return [
                {
                    "id": r.id,
                    "type": r.artifact_type,
                    "checksum": r.checksum,
                    "created_at": r.created_at.isoformat(),
                    "media_type": next(
                        (m for ext, m in media.items() if r.path.endswith(ext)),
                        "application/octet-stream",
                    ),
                }
                for r in rows
            ]
