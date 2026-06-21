"""Explicit API response DTOs for optimization (second Codex review, Medium finding #19).

Responses expose ONLY reviewed fields. Domain models are never returned directly, so a new
internal field cannot silently become public. In particular these views exclude: the mutable
internal evidence object (only reviewed, bounded evidence fields are surfaced), internal
filesystem paths (artifacts expose type + checksum, not on-disk paths), internal process
details (raw runtimes / resource usage), problem execution limits, and raw provenance.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from orbitmind.optimization.models import (
    BenchmarkComparison,
    BenchmarkRun,
    QuantumExperiment,
    SchedulingProblem,
    SolverResult,
)


class _View(BaseModel):
    # Forbid extra so the view is a strict allowlist; new domain fields do not leak in.
    model_config = ConfigDict(extra="forbid")


class WindowView(_View):
    start: str
    end: str


class OpportunityView(_View):
    id: str
    satellite_id: str
    target_id: str
    window: WindowView
    mission_value: float
    duration_seconds: float
    energy_cost: float
    storage_cost: float
    priority: int
    provenance: str


class ProblemView(_View):
    id: str
    name: str
    checksum: str
    num_variables: int
    source: str
    epistemic_status: str
    limitations: str
    opportunities: list[OpportunityView]

    @classmethod
    def from_domain(cls, p: SchedulingProblem) -> ProblemView:
        return cls(
            id=p.id,
            name=p.name,
            checksum=p.checksum,
            num_variables=len(p.opportunities),
            source=p.source,
            epistemic_status=p.epistemic_status.value,
            limitations=p.limitations,
            opportunities=[
                OpportunityView(
                    id=o.id,
                    satellite_id=o.satellite_id,
                    target_id=o.target_id,
                    window=WindowView(
                        start=o.window.start.isoformat(), end=o.window.end.isoformat()
                    ),
                    mission_value=o.mission_value,
                    duration_seconds=o.duration_seconds,
                    energy_cost=o.energy_cost,
                    storage_cost=o.storage_cost,
                    priority=o.priority,
                    provenance=o.provenance,
                )
                for o in p.opportunities
            ],
        )


class SolverResultView(_View):
    id: str
    solver_kind: str
    solver_name: str
    solver_version: str
    status: str
    optimality_status: str
    objective_value: float | None
    known_optimum: float | None
    objective_gap: float | None
    feasible: bool
    selected_opportunity_ids: list[str]

    @classmethod
    def from_domain(cls, r: SolverResult) -> SolverResultView:
        selected = list(r.schedule.selected_opportunity_ids) if r.schedule is not None else []
        return cls(
            id=r.id,
            solver_kind=r.solver_kind.value,
            solver_name=r.solver_name,
            solver_version=r.solver_version,
            status=r.status.value,
            optimality_status=r.optimality_status.value,
            objective_value=r.objective_value,
            known_optimum=r.known_optimum,
            objective_gap=r.objective_gap,
            feasible=r.feasible,
            selected_opportunity_ids=selected,
        )


class QuantumExperimentView(_View):
    id: str
    status: str
    qubits: int | None
    depth: int | None
    shots: int
    total_shots: int
    distinct_samples: int
    feasible_sample_ratio: float
    objective_gap: float | None
    exact_optimum_in_samples: bool | None
    best_feasible_objective: float | None
    # Reviewed, bounded evidence fields (NOT the mutable evidence object).
    qubo_checksum: str | None
    manifest_checksum: str | None
    penalty_proof_status: str | None
    bit_order: str | None
    limitations: str

    @classmethod
    def from_domain(cls, q: QuantumExperiment) -> QuantumExperimentView:
        ev = q.evidence
        return cls(
            id=q.id,
            status=q.status.value,
            qubits=q.circuit_metadata.qubits if q.circuit_metadata else None,
            depth=q.circuit_metadata.depth if q.circuit_metadata else None,
            shots=q.configuration.shots,
            total_shots=q.total_shots,
            distinct_samples=q.distinct_samples,
            feasible_sample_ratio=q.feasible_sample_ratio,
            objective_gap=q.objective_gap,
            exact_optimum_in_samples=q.exact_optimum_in_samples,
            best_feasible_objective=(
                q.best_feasible_sample.objective_value if q.best_feasible_sample else None
            ),
            qubo_checksum=ev.qubo_checksum if ev else None,
            manifest_checksum=ev.manifest_checksum if ev else None,
            penalty_proof_status=ev.penalty_proof_status if ev else None,
            bit_order=ev.bit_order if ev else None,
            limitations=q.limitations,
        )


class ComparisonView(_View):
    conclusion: str
    exact_objective: float | None
    greedy_objective: float | None
    quantum_objective: float | None
    known_optimum: float | None
    objective_gap: float | None
    policy_id: str
    policy_version: str
    competitive_relative_gap: float
    min_feasible_sample_ratio: float
    rationale: str
    epistemic_status: str
    limitations: str

    @classmethod
    def from_domain(cls, c: BenchmarkComparison) -> ComparisonView:
        return cls(
            conclusion=c.conclusion.value,
            exact_objective=c.exact_objective,
            greedy_objective=c.greedy_objective,
            quantum_objective=c.quantum_objective,
            known_optimum=c.known_optimum,
            objective_gap=c.objective_gap,
            policy_id=c.policy_id,
            policy_version=c.policy_version,
            competitive_relative_gap=c.thresholds.competitive_relative_gap,
            min_feasible_sample_ratio=c.thresholds.min_feasible_sample_ratio,
            rationale=c.rationale,
            epistemic_status=c.epistemic_status.value,
            limitations=c.limitations,
        )


class ArtifactView(_View):
    type: str
    checksum: str  # on-disk paths are NOT exposed; retrieve via the artifacts endpoint by id


class BenchmarkView(_View):
    id: str
    problem_checksum: str
    conclusion: str | None
    verified: bool
    solver_results: list[SolverResultView]
    quantum: QuantumExperimentView | None
    comparison: ComparisonView | None
    artifacts: list[ArtifactView]

    @classmethod
    def from_domain(cls, run: BenchmarkRun, *, verified: bool) -> BenchmarkView:
        return cls(
            id=run.id,
            problem_checksum=run.problem_checksum,
            conclusion=run.comparison.conclusion.value if run.comparison else None,
            verified=verified,
            solver_results=[SolverResultView.from_domain(r) for r in run.solver_results],
            quantum=(
                QuantumExperimentView.from_domain(run.quantum_experiment)
                if run.quantum_experiment is not None
                else None
            ),
            comparison=(
                ComparisonView.from_domain(run.comparison) if run.comparison is not None else None
            ),
            artifacts=[
                ArtifactView(type=a.get("type", ""), checksum=a.get("checksum", ""))
                for a in run.artifacts
            ],
        )
