"""SQLAlchemy repository for scheduling optimization (Phase 4A)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.optimization.models import (
    BenchmarkComparison,
    BenchmarkRun,
    BenchmarkThresholds,
    QuantumExperiment,
    SchedulingProblem,
    SolverResult,
)
from orbitmind.optimization.receipts import BenchmarkExecutionReceipt
from orbitmind.persistence.optimization_models import (
    BenchmarkComparisonRow,
    BenchmarkExecutionReceiptRow,
    BenchmarkRunRow,
    ObservationOpportunityRow,
    OptimizationArtifactRow,
    OptimizationProblemRow,
    QuantumExperimentRow,
    QuantumSampleResultRow,
    SchedulingConstraintRow,
    SolverRunRow,
)

# Integrity classifications for a persisted-evidence load (fifth review, Critical + High #2).
INTEGRITY_OK = "ok"
INTEGRITY_NOT_FOUND = "not-found"
INTEGRITY_MALFORMED = "malformed-persisted-evidence"
INTEGRITY_SAMPLE_MISMATCH = "sample-row-mismatch"


@dataclass(frozen=True)
class EvidenceLoadResult:
    """Outcome of safely reconstructing persisted benchmark evidence. Malformed persisted data
    NEVER escapes as an uncaught exception (fifth review, High #2); duplicate sample
    representations that disagree fail closed (fifth review, Critical). Denormalized row scalars
    are always populated (even when the JSON is malformed) so public reads can render a bounded
    integrity response without trusting the malformed payload."""

    found: bool
    integrity_status: str
    problem: SchedulingProblem | None = None
    run: BenchmarkRun | None = None
    receipt: BenchmarkExecutionReceipt | None = None
    findings: tuple[str, ...] = ()
    benchmark_id: str | None = None
    problem_id: str | None = None
    problem_checksum: str | None = None
    created_at_iso: str | None = None
    artifact_count: int = 0
    has_quantum: bool = False

    @property
    def is_ok(self) -> bool:
        return self.integrity_status == INTEGRITY_OK


class PersistedBenchmarkThresholds(BaseModel):
    """STRICT persistence-only DTO for stored comparison thresholds (final acceptance, High #2 +
    Medium).

    No defaults: a persisted ``{}`` / partial JSON, an extra field, a non-finite value, or an
    out-of-range value is malformed evidence — NOT an excuse to synthesize trusted defaults. JSON
    numeric STRINGS (``"0.0"``) and booleans (``true``/``false``) are NEVER coerced — Python bool
    is an int subtype, so it is rejected explicitly. JSON integers (``0``/``1``) are accepted as
    valid numbers (documented decision). Used ONLY when reading historical persisted evidence; new
    server policies still create thresholds with their own defaults.
    """

    model_config = ConfigDict(extra="forbid")

    competitive_relative_gap: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    min_feasible_sample_ratio: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @field_validator(
        "competitive_relative_gap", "min_feasible_sample_ratio", mode="before"
    )
    @classmethod
    def _require_real_number(cls, value: object) -> object:
        # Reject before Pydantic coercion. bool is an int subclass -> reject explicitly; a JSON
        # numeric string ("0.0") must never be accepted. Only a real int/float is a valid number.
        if isinstance(value, bool):
            raise ValueError("boolean is not a valid threshold")
        if type(value) not in (int, float):
            raise ValueError("threshold must be a JSON number, not a string/bool/null/collection")
        return value


def _persisted_thresholds(raw: Any) -> BenchmarkThresholds:
    """Validate stored thresholds with the strict DTO, then map to the domain model. Raises on
    malformed evidence (caught by load_evidence and classified as malformed-persisted-evidence)."""
    strict = PersistedBenchmarkThresholds.model_validate(raw)
    return BenchmarkThresholds(
        competitive_relative_gap=strict.competitive_relative_gap,
        min_feasible_sample_ratio=strict.min_feasible_sample_ratio,
    )


def _sample_key(s: Any) -> tuple[str, int, float, bool, float, float, float, int]:
    """Canonical comparison key shared by domain samples and persisted child rows."""
    return (
        str(s.bitstring),
        int(s.count),
        float(s.probability),
        bool(s.feasible),
        float(s.raw_mission_value),
        float(s.objective_value),
        float(s.qubo_energy),
        int(s.violations_count),
    )


class SqlAlchemyOptimizationRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    # ---- problems ----------------------------------------------------------
    def find_problem_by_checksum(self, checksum: str) -> OptimizationProblemRow | None:
        return (
            self._s.execute(
                select(OptimizationProblemRow).where(OptimizationProblemRow.checksum == checksum)
            )
            .scalars()
            .first()
        )

    def save_problem(self, problem: SchedulingProblem) -> str:
        """Idempotent, race-safe get-or-create keyed by the canonical checksum (finding #9).

        Returns the EXISTING persisted id when the same problem already exists (incl. when a
        concurrent transaction wins the unique-checksum race). The outer transaction remains
        usable after a conflict (the insert is wrapped in a SAVEPOINT).
        """
        existing = self.find_problem_by_checksum(problem.checksum)
        if existing is not None:
            return existing.id
        try:
            with self._s.begin_nested():  # SAVEPOINT
                self._s.add(
                    OptimizationProblemRow(
                        id=problem.id,
                        name=problem.name,
                        checksum=problem.checksum,
                        num_variables=len(problem.opportunities),
                        source=problem.source,
                        provenance=problem.provenance,
                        epistemic_status=problem.epistemic_status.value,
                        limitations=problem.limitations,
                        problem_json=problem.model_dump(mode="json"),
                        created_at=problem.created_at,
                    )
                )
                self._s.flush()  # parent must exist before FK children (PostgreSQL FKs)
                for opp in problem.opportunities:
                    self._s.add(
                        ObservationOpportunityRow(
                            id=new_id(),
                            problem_id=problem.id,
                            opportunity_id=opp.id,
                            satellite_id=opp.satellite_id,
                            target_id=opp.target_id,
                            start_at=opp.window.start,
                            end_at=opp.window.end,
                            mission_value=opp.mission_value,
                            duration_seconds=opp.duration_seconds,
                            energy_cost=opp.energy_cost,
                            storage_cost=opp.storage_cost,
                            pointing_cost=opp.pointing_cost,
                            priority=opp.priority,
                        )
                    )
                self._add_constraint_rows(problem)
        except IntegrityError:
            # A concurrent insert won the unique-checksum race; re-query and return its id.
            self._s.expire_all()
            won = self.find_problem_by_checksum(problem.checksum)
            if won is None:  # pragma: no cover - re-raise if it was a different integrity error
                raise
            return won.id
        return problem.id

    def _add_constraint_rows(self, problem: SchedulingProblem) -> None:
        c = problem.constraints
        rows: list[tuple[str, dict[str, Any]]] = []
        if c.enforce_no_overlap:
            rows.append(("no-overlap", {"enforced": True}))
        if c.max_observations is not None:
            rows.append(("max-observations", {"limit": c.max_observations}))
        if c.mutually_exclusive:
            rows.append(("mutual-exclusion", {"pairs": [list(p) for p in c.mutually_exclusive]}))
        if c.mandatory:
            rows.append(("mandatory", {"opportunities": list(c.mandatory)}))
        if c.per_target_limit is not None:
            rows.append(("per-target-limit", {"limit": c.per_target_limit}))
        if c.min_mission_value is not None:
            rows.append(("min-mission-value", {"min": c.min_mission_value}))
        if c.enforce_energy_capacity:
            rows.append(("energy-capacity", {"enforced": True}))
        if c.enforce_storage_capacity:
            rows.append(("storage-capacity", {"enforced": True}))
        for kind, detail in rows:
            self._s.add(
                SchedulingConstraintRow(
                    id=new_id(), problem_id=problem.id, kind=kind, detail_json=detail
                )
            )

    def get_problem(self, problem_id: str) -> SchedulingProblem | None:
        row = self._s.get(OptimizationProblemRow, problem_id)
        return SchedulingProblem.model_validate(row.problem_json) if row is not None else None

    def count_problems(self) -> int:
        return int(
            self._s.execute(select(func.count()).select_from(OptimizationProblemRow)).scalar_one()
        )

    def list_problems(self, limit: int, offset: int) -> list[SchedulingProblem]:
        rows = (
            self._s.execute(
                select(OptimizationProblemRow)
                .order_by(OptimizationProblemRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [SchedulingProblem.model_validate(r.problem_json) for r in rows]

    # ---- solver runs + quantum experiments --------------------------------
    def save_solver_result(
        self, result: SolverResult, *, benchmark_id: str | None, problem_id: str | None
    ) -> None:
        self._s.add(
            SolverRunRow(
                id=result.id,
                benchmark_id=benchmark_id,
                problem_id=problem_id,
                problem_checksum=result.problem_checksum,
                solver_kind=result.solver_kind.value,
                solver_name=result.solver_name,
                solver_version=result.solver_version,
                status=result.status.value,
                optimality_status=result.optimality_status.value,
                objective_value=result.objective_value,
                known_optimum=result.known_optimum,
                objective_gap=result.objective_gap,
                feasible=result.feasible,
                seed=result.seed,
                runtime_seconds=result.runtime_seconds,
                config_json=result.configuration.model_dump(mode="json"),
                result_json=result.model_dump(mode="json"),
                software_versions=result.software_versions,
                created_at=utcnow(),
            )
        )

    def save_quantum_experiment(
        self, experiment: QuantumExperiment, *, benchmark_id: str | None, problem_id: str | None
    ) -> None:
        meta = experiment.circuit_metadata
        self._s.add(
            QuantumExperimentRow(
                id=experiment.id,
                benchmark_id=benchmark_id,
                problem_id=problem_id,
                problem_checksum=experiment.problem_checksum,
                status=experiment.status.value,
                qubits=meta.qubits if meta else None,
                depth=meta.depth if meta else None,
                shots=experiment.configuration.shots,
                optimizer_iterations=meta.optimizer_iterations if meta else 0,
                qaoa_layers=experiment.configuration.qaoa_layers,
                total_shots=experiment.total_shots,
                distinct_samples=experiment.distinct_samples,
                feasible_sample_ratio=experiment.feasible_sample_ratio,
                objective_gap=experiment.objective_gap,
                exact_optimum_in_samples=experiment.exact_optimum_in_samples,
                seed=experiment.seed,
                runtime_seconds=experiment.runtime_seconds,
                circuit_metadata_json=meta.model_dump(mode="json") if meta else None,
                experiment_json=experiment.model_dump(mode="json"),
                software_versions=experiment.software_versions,
                created_at=utcnow(),
            )
        )
        self._s.flush()  # experiment row must exist before its FK sample rows
        for sample in experiment.samples:
            self._s.add(
                QuantumSampleResultRow(
                    id=new_id(),
                    experiment_id=experiment.id,
                    bitstring=sample.bitstring,
                    count=sample.count,
                    probability=sample.probability,
                    feasible=sample.feasible,
                    raw_mission_value=sample.raw_mission_value,
                    objective_value=sample.objective_value,
                    qubo_energy=sample.qubo_energy,
                    violations_count=sample.violations_count,
                )
            )

    def save_comparison(self, comparison: BenchmarkComparison, *, benchmark_id: str) -> None:
        self._s.add(
            BenchmarkComparisonRow(
                id=comparison.id,
                benchmark_id=benchmark_id,
                problem_id=comparison.problem_id,
                problem_checksum=comparison.problem_checksum,
                conclusion=comparison.conclusion.value,
                exact_objective=comparison.exact_objective,
                greedy_objective=comparison.greedy_objective,
                quantum_objective=comparison.quantum_objective,
                known_optimum=comparison.known_optimum,
                objective_gap=comparison.objective_gap,
                exact_result_id=comparison.exact_result_id,
                greedy_result_id=comparison.greedy_result_id,
                quantum_experiment_id=comparison.quantum_experiment_id,
                policy_id=comparison.policy_id,
                policy_version=comparison.policy_version,
                policy_checksum=comparison.policy_checksum,
                rationale=comparison.rationale,
                thresholds_json=comparison.thresholds.model_dump(mode="json"),
                epistemic_status=comparison.epistemic_status.value,
                limitations=comparison.limitations,
                created_at=comparison.created_at,
            )
        )

    def save_benchmark(
        self, run: BenchmarkRun, *, problem_id: str | None, verification_passed: bool
    ) -> str:
        self._s.add(
            BenchmarkRunRow(
                id=run.id,
                problem_id=problem_id,
                problem_checksum=run.problem_checksum,
                conclusion=run.comparison.conclusion.value if run.comparison else "unknown",
                verification_passed=verification_passed,
                policy_id=str(run.policy_snapshot["policy_id"]) if run.policy_snapshot else None,
                policy_version=(
                    str(run.policy_snapshot["policy_version"]) if run.policy_snapshot else None
                ),
                policy_checksum=(
                    str(run.policy_snapshot["checksum"]) if run.policy_snapshot else None
                ),
                policy_snapshot_json=run.policy_snapshot,
                created_at=run.created_at,
            )
        )
        # The parent benchmark row must exist before its FK children (solver runs, quantum
        # experiment, comparison, artifacts). These mappers have no ORM relationship(), so the
        # unit-of-work does not order them by the table FK on its own; flush explicitly, as
        # save_problem/save_quantum_experiment do, or PostgreSQL rejects the child inserts.
        self._s.flush()
        for result in run.solver_results:
            self.save_solver_result(result, benchmark_id=run.id, problem_id=problem_id)
        if run.quantum_experiment is not None:
            self.save_quantum_experiment(
                run.quantum_experiment, benchmark_id=run.id, problem_id=problem_id
            )
        # The comparison's composite ownership FKs reference (benchmark_id, id) on solver_runs and
        # quantum_experiments, so those rows must exist before the comparison is inserted.
        self._s.flush()
        if run.comparison is not None:
            self.save_comparison(run.comparison, benchmark_id=run.id)
        for art in run.artifacts:
            self._s.add(
                OptimizationArtifactRow(
                    id=new_id(),
                    scope_id=run.id,
                    artifact_type=art.get("type", ""),
                    path=art.get("path", ""),
                    sidecar_path=art.get("sidecar_path", ""),
                    checksum=art.get("checksum", ""),
                    created_at=utcnow(),
                )
            )
        return run.id

    # ---- reads -------------------------------------------------------------
    def get_solver_run(self, run_id: str) -> SolverResult | QuantumExperiment | None:
        row = self._s.get(SolverRunRow, run_id)
        if row is not None:
            return SolverResult.model_validate(row.result_json)
        qrow = self._s.get(QuantumExperimentRow, run_id)
        if qrow is not None:
            return QuantumExperiment.model_validate(qrow.experiment_json)
        return None

    def list_runs(self, limit: int, offset: int) -> list[dict[str, object]]:
        rows = (
            self._s.execute(
                select(SolverRunRow)
                .order_by(SolverRunRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return [
            {
                "id": r.id,
                "kind": r.solver_kind,
                "solver": r.solver_name,
                "status": r.status,
                "objective_value": r.objective_value,
                "feasible": r.feasible,
                "problem_checksum": r.problem_checksum,
                "benchmark_id": r.benchmark_id,
            }
            for r in rows
        ]

    def get_benchmark(self, benchmark_id: str) -> BenchmarkRunRow | None:
        return self._s.get(BenchmarkRunRow, benchmark_id)

    def list_benchmark_ids(self, limit: int, offset: int) -> list[str]:
        rows = (
            self._s.execute(
                select(BenchmarkRunRow.id)
                .order_by(BenchmarkRunRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            .scalars()
            .all()
        )
        return list(rows)

    def _quantum_sample_rows(self, experiment_id: str) -> list[QuantumSampleResultRow]:
        return list(
            self._s.execute(
                select(QuantumSampleResultRow).where(
                    QuantumSampleResultRow.experiment_id == experiment_id
                )
            )
            .scalars()
            .all()
        )

    def load_evidence(self, benchmark_id: str) -> EvidenceLoadResult:
        """Safely reconstruct the full domain benchmark + receipt for read-time
        re-authentication (fourth review, Critical #2; fifth review, Critical + High #2).

        Malformed persisted JSON is classified rather than raised, and the authoritative parent
        experiment samples are verified for COMPLETE EQUALITY against the persisted
        ``quantum_sample_results`` child rows so a tampered child copy fails closed.
        """
        row = self._s.get(BenchmarkRunRow, benchmark_id)
        if row is None:
            return EvidenceLoadResult(found=False, integrity_status=INTEGRITY_NOT_FOUND)
        qrow = (
            self._s.execute(
                select(QuantumExperimentRow).where(
                    QuantumExperimentRow.benchmark_id == benchmark_id
                )
            )
            .scalars()
            .first()
        )
        bench_id: str = row.id
        prob_id: str | None = row.problem_id
        prob_checksum: str = row.problem_checksum
        created_iso: str | None = row.created_at.isoformat() if row.created_at else None
        art_count: int = len(self.get_artifacts(benchmark_id))
        has_q: bool = qrow is not None
        try:
            if row.problem_id is None:
                raise ValueError("benchmark row has no problem_id")
            problem = self.get_problem(row.problem_id)
            if problem is None:
                raise ValueError("benchmark problem is missing")
            solver_rows = (
                self._s.execute(
                    select(SolverRunRow).where(SolverRunRow.benchmark_id == benchmark_id)
                )
                .scalars()
                .all()
            )
            solver_results = [SolverResult.model_validate(r.result_json) for r in solver_rows]
            quantum = QuantumExperiment.model_validate(qrow.experiment_json) if qrow else None
            comparison = self.get_comparison(benchmark_id)
            artifacts = [
                {
                    "type": a.artifact_type,
                    "path": a.path,
                    "sidecar_path": a.sidecar_path,
                    "checksum": a.checksum,
                }
                for a in self.get_artifacts(benchmark_id)
            ]
            run = BenchmarkRun(
                id=row.id,
                problem_id=row.problem_id,
                problem_checksum=row.problem_checksum,
                policy_snapshot=row.policy_snapshot_json,
                solver_results=solver_results,
                quantum_experiment=quantum,
                comparison=comparison,
                artifacts=artifacts,
            )
            receipt_row = self.get_receipt(benchmark_id)
            receipt = (
                BenchmarkExecutionReceipt.model_validate(
                    {
                        "payload": receipt_row.payload_json,
                        "payload_checksum": receipt_row.payload_checksum,
                        "signature": receipt_row.signature,
                    }
                )
                if receipt_row is not None
                else None
            )
        except (ValidationError, ValueError, TypeError, LookupError, AttributeError) as exc:
            # Malformed persisted evidence must FAIL CLOSED, never raise (fifth review, High #2).
            return EvidenceLoadResult(
                found=True,
                integrity_status=INTEGRITY_MALFORMED,
                findings=(f"{type(exc).__name__}: persisted evidence failed reconstruction",),
                benchmark_id=bench_id,
                problem_id=prob_id,
                problem_checksum=prob_checksum,
                created_at_iso=created_iso,
                artifact_count=art_count,
                has_quantum=has_q,
            )
        # Canonical sample representation: the authoritative parent samples must EXACTLY equal the
        # persisted child rows (fifth review, Critical) — a tampered child copy is undetectable to
        # semantic re-verification (which only sees the parent), so it is caught here.
        if quantum is not None and qrow is not None:
            parent = sorted(_sample_key(s) for s in quantum.samples)
            child = sorted(_sample_key(r) for r in self._quantum_sample_rows(qrow.id))
            if parent != child:
                return EvidenceLoadResult(
                    found=True,
                    integrity_status=INTEGRITY_SAMPLE_MISMATCH,
                    problem=problem,
                    run=run,
                    receipt=receipt,
                    findings=("quantum sample child rows disagree with the authoritative samples",),
                    benchmark_id=bench_id,
                    problem_id=prob_id,
                    problem_checksum=prob_checksum,
                    created_at_iso=created_iso,
                    artifact_count=art_count,
                    has_quantum=has_q,
                )
        return EvidenceLoadResult(
            found=True,
            integrity_status=INTEGRITY_OK,
            problem=problem,
            run=run,
            receipt=receipt,
            benchmark_id=bench_id,
            problem_id=prob_id,
            problem_checksum=prob_checksum,
            created_at_iso=created_iso,
            artifact_count=art_count,
            has_quantum=has_q,
        )

    # ---- execution receipts (third review, High #1) ------------------------
    def save_receipt(self, receipt: BenchmarkExecutionReceipt) -> None:
        p = receipt.payload
        self._s.add(
            BenchmarkExecutionReceiptRow(
                id=p.receipt_id,
                benchmark_id=p.benchmark_id,
                signer_key_id=p.signer_key_id,
                signature_algorithm=p.signature_algorithm,
                payload_checksum=receipt.payload_checksum,
                signature=receipt.signature,
                worker_execution_nonce=p.worker_execution_nonce,
                payload_json=p.model_dump(mode="json"),
                created_at=utcnow(),
            )
        )

    def get_receipt(self, benchmark_id: str) -> BenchmarkExecutionReceiptRow | None:
        return (
            self._s.execute(
                select(BenchmarkExecutionReceiptRow).where(
                    BenchmarkExecutionReceiptRow.benchmark_id == benchmark_id
                )
            )
            .scalars()
            .first()
        )

    def get_comparison(self, benchmark_id: str) -> BenchmarkComparison | None:
        row = (
            self._s.execute(
                select(BenchmarkComparisonRow).where(
                    BenchmarkComparisonRow.benchmark_id == benchmark_id
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            return None
        # Exact round-trip incl. associations, objective gap, policy metadata, thresholds,
        # epistemic status, limitations (review findings #12/#17).
        return BenchmarkComparison(
            id=row.id,
            benchmark_id=row.benchmark_id,
            problem_id=row.problem_id,
            problem_checksum=row.problem_checksum,
            exact_result_id=row.exact_result_id,
            greedy_result_id=row.greedy_result_id,
            quantum_experiment_id=row.quantum_experiment_id,
            conclusion=row.conclusion,  # type: ignore[arg-type]
            exact_objective=row.exact_objective,
            greedy_objective=row.greedy_objective,
            quantum_objective=row.quantum_objective,
            known_optimum=row.known_optimum,
            objective_gap=row.objective_gap,
            thresholds=_persisted_thresholds(row.thresholds_json),
            policy_id=row.policy_id,
            policy_version=row.policy_version,
            policy_checksum=row.policy_checksum,
            rationale=row.rationale,
            epistemic_status=row.epistemic_status,  # type: ignore[arg-type]
            limitations=row.limitations,
            created_at=row.created_at,
        )

    def get_artifacts(self, scope_id: str) -> list[OptimizationArtifactRow]:
        return list(
            self._s.execute(
                select(OptimizationArtifactRow).where(OptimizationArtifactRow.scope_id == scope_id)
            )
            .scalars()
            .all()
        )
