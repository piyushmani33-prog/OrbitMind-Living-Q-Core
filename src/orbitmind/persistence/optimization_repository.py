"""SQLAlchemy repository for scheduling optimization (Phase 4A)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.optimization.models import (
    BenchmarkComparison,
    BenchmarkRun,
    QuantumExperiment,
    SchedulingProblem,
    SolverResult,
)
from orbitmind.persistence.optimization_models import (
    BenchmarkComparisonRow,
    BenchmarkRunRow,
    ObservationOpportunityRow,
    OptimizationArtifactRow,
    OptimizationProblemRow,
    QuantumExperimentRow,
    QuantumSampleResultRow,
    SchedulingConstraintRow,
    SolverRunRow,
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
        existing = self.find_problem_by_checksum(problem.checksum)
        if existing is not None:
            return existing.id
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
        self._s.flush()  # parent must exist before FK children (PostgreSQL enforces FKs)
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
        self, experiment: QuantumExperiment, *, benchmark_id: str | None
    ) -> None:
        meta = experiment.circuit_metadata
        self._s.add(
            QuantumExperimentRow(
                id=experiment.id,
                benchmark_id=benchmark_id,
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
                problem_checksum=comparison.problem_checksum,
                conclusion=comparison.conclusion.value,
                exact_objective=comparison.exact_objective,
                greedy_objective=comparison.greedy_objective,
                quantum_objective=comparison.quantum_objective,
                known_optimum=comparison.known_optimum,
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
                created_at=run.created_at,
            )
        )
        for result in run.solver_results:
            self.save_solver_result(result, benchmark_id=run.id, problem_id=problem_id)
        if run.quantum_experiment is not None:
            self.save_quantum_experiment(run.quantum_experiment, benchmark_id=run.id)
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
        return BenchmarkComparison(
            id=row.id,
            problem_checksum=row.problem_checksum,
            conclusion=row.conclusion,  # type: ignore[arg-type]
            exact_objective=row.exact_objective,
            greedy_objective=row.greedy_objective,
            quantum_objective=row.quantum_objective,
            known_optimum=row.known_optimum,
            rationale=row.rationale,
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
