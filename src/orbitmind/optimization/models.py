"""Typed domain models for bounded satellite observation scheduling (Phase 4A).

Separate from persistence (ORM) and API schemas. All datetimes are timezone-aware UTC;
all resource costs are nonnegative; mission values are bounded.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class SolverKind(StrEnum):
    EXACT = "exact"
    GREEDY = "greedy"
    QUANTUM_QAOA = "quantum-qaoa"


class ConstraintKind(StrEnum):
    NO_OVERLAP = "no-overlap"  # same satellite, overlapping time windows
    MAX_OBSERVATIONS = "max-observations"
    ENERGY_CAPACITY = "energy-capacity"
    STORAGE_CAPACITY = "storage-capacity"
    MUTUAL_EXCLUSION = "mutual-exclusion"
    MANDATORY = "mandatory"
    PER_TARGET_LIMIT = "per-target-limit"
    MIN_MISSION_VALUE = "min-mission-value"


class OptimalityStatus(StrEnum):
    OPTIMAL = "optimal"  # proven optimal (exact solver on a small instance)
    FEASIBLE = "feasible"  # a feasible solution, optimality unknown
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


class ExperimentStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"
    UNSUPPORTED = "unsupported"
    INCONCLUSIVE = "inconclusive"


class ComparisonConclusion(StrEnum):
    CLASSICAL_EXACT_BEST = "classical-exact-best"
    CLASSICAL_GREEDY_BEST = "classical-greedy-best"
    QUANTUM_COMPETITIVE = "quantum-competitive"  # met a bounded threshold; NOT advantage
    QUANTUM_WORSE = "quantum-worse"
    QUANTUM_INFEASIBLE = "quantum-infeasible"
    EQUIVALENT_OBJECTIVE = "equivalent-objective"
    INSUFFICIENT_EVIDENCE = "insufficient-evidence"
    EXPERIMENT_FAILED = "experiment-failed"


# --------------------------------------------------------------------------
# Problem structure
# --------------------------------------------------------------------------
class TimeWindow(BaseModel):
    model_config = ConfigDict(frozen=True)

    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _check(self) -> TimeWindow:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("time windows must be timezone-aware (UTC)")
        if self.end <= self.start:
            raise ValueError("time window end must be after start")
        return self

    def overlaps(self, other: TimeWindow) -> bool:
        return self.start < other.end and other.start < self.end


class ObservationTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    priority: int = Field(default=1, ge=0)


class SatelliteResource(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    energy_capacity: float = Field(ge=0.0)
    storage_capacity: float = Field(ge=0.0)


class ObservationOpportunity(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    satellite_id: str
    target_id: str
    window: TimeWindow
    mission_value: float = Field(ge=0.0, le=1_000_000.0)
    duration_seconds: float = Field(gt=0.0)
    energy_cost: float = Field(ge=0.0)
    storage_cost: float = Field(ge=0.0)
    pointing_cost: float = Field(default=0.0, ge=0.0)
    priority: int = Field(default=1, ge=0)
    source: str = "fixture"
    provenance: str = "bundled deterministic fixture; not live CelesTrak/JPL data"
    limitations: str = ""


class SchedulingConflict(BaseModel):
    model_config = ConfigDict(frozen=True)

    opportunity_a: str
    opportunity_b: str
    kind: ConstraintKind  # NO_OVERLAP or MUTUAL_EXCLUSION


class SchedulingObjective(BaseModel):
    model_config = ConfigDict(frozen=True)

    mission_value_weight: float = 1.0
    # Penalty coefficient applied per violated pairwise/mandatory constraint in the QUBO
    # and in the penalized objective. None => auto (total mission value + 1), a value
    # provably large enough that violating a constraint can never be optimal.
    penalty_coefficient: float | None = None


class ConstraintSet(BaseModel):
    """The bounded, deterministic constraints applied to a scheduling problem."""

    model_config = ConfigDict(frozen=True)

    max_observations: int | None = Field(default=None, ge=0)
    mutually_exclusive: tuple[tuple[str, str], ...] = ()
    mandatory: tuple[str, ...] = ()
    per_target_limit: int | None = Field(default=None, ge=1)
    min_mission_value: float | None = Field(default=None, ge=0.0)
    enforce_no_overlap: bool = True
    enforce_energy_capacity: bool = True
    enforce_storage_capacity: bool = True


class SchedulingProblemLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_variables: int = Field(default=20, ge=1, le=24)
    exact_max_variables: int = Field(default=20, ge=1, le=22)
    max_shots: int = Field(default=8192, ge=1, le=65536)
    max_optimizer_iterations: int = Field(default=64, ge=1, le=512)
    max_timeout_seconds: float = Field(default=30.0, gt=0.0, le=120.0)


class SchedulingProblem(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    opportunities: list[ObservationOpportunity]
    satellites: list[SatelliteResource] = Field(default_factory=list)
    targets: list[ObservationTarget] = Field(default_factory=list)
    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    objective: SchedulingObjective = Field(default_factory=SchedulingObjective)
    limits: SchedulingProblemLimits = Field(default_factory=SchedulingProblemLimits)
    source: str = "fixture"
    provenance: str = "bundled deterministic fixture"
    limitations: str = "bounded benchmark instance; not an operational tasking plan"
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION
    checksum: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Evaluation (shared deterministic verifier output)
# --------------------------------------------------------------------------
class ConstraintViolation(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: ConstraintKind
    detail: str
    magnitude: float = 0.0


class CandidateSchedule(BaseModel):
    model_config = ConfigDict(frozen=True)

    problem_checksum: str
    selected_opportunity_ids: tuple[str, ...]
    produced_by: str = ""

    def bitstring(self, order: tuple[str, ...]) -> str:
        selected = set(self.selected_opportunity_ids)
        return "".join("1" if opp_id in selected else "0" for opp_id in order)


class ScheduleEvaluation(BaseModel):
    model_config = ConfigDict(frozen=True)

    problem_checksum: str
    selected_opportunity_ids: tuple[str, ...]
    feasible: bool
    raw_mission_value: float  # unweighted sum of selected mission values
    weighted_mission_value: float  # sum of mission_value * mission_value_weight
    constraint_penalty: float  # penalty for QUBO-encoded (pairwise/mandatory) violations
    penalized_objective: float  # weighted_mission_value - constraint_penalty (== -QUBO energy)
    objective_value: float  # weighted mission value used for ranking feasible schedules
    total_energy: float
    total_storage: float
    violations: tuple[ConstraintViolation, ...]
    evaluated_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# QUBO
# --------------------------------------------------------------------------
class QuboModel(BaseModel):
    """A minimize-energy QUBO: E(x) = offset + sum_i linear_i x_i + sum_{i<j} quad_ij x_i x_j.

    Energy is defined so that minimizing E maximizes the penalized objective
    (E(x) == -penalized_objective(x)).
    """

    model_config = ConfigDict(frozen=True)

    num_vars: int
    variable_opportunities: tuple[str, ...]  # var index -> opportunity id (stable order)
    linear: dict[int, float]
    quadratic: dict[str, float]  # "i,j" (i<j) -> coefficient
    offset: float
    penalty_coefficient: float
    penalty_explanation: str
    checksum: str = ""


# --------------------------------------------------------------------------
# Solver configuration + results
# --------------------------------------------------------------------------
class SolverConfiguration(BaseModel):
    model_config = ConfigDict(frozen=True)

    solver_kind: SolverKind
    seed: int = 1
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    # Quantum-only knobs (ignored by classical solvers).
    shots: int = Field(default=2048, ge=1)
    optimizer_iterations: int = Field(default=24, ge=1)
    qaoa_layers: int = Field(default=1, ge=1, le=3)
    backend: str = "AerSimulator"
    transpile_level: int = Field(default=1, ge=0, le=3)


class ResourceUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    evaluated_candidates: int = 0
    wall_clock_seconds: float = 0.0


class SolverResult(BaseModel):
    id: str = Field(default_factory=new_id)
    solver_kind: SolverKind
    solver_name: str
    solver_version: str
    problem_checksum: str
    configuration: SolverConfiguration
    status: ExperimentStatus
    schedule: CandidateSchedule | None = None
    evaluation: ScheduleEvaluation | None = None
    optimality_status: OptimalityStatus = OptimalityStatus.UNKNOWN
    objective_value: float | None = None
    known_optimum: float | None = None
    objective_gap: float | None = None  # known_optimum - objective_value (>=0 when known)
    feasible: bool = False
    seed: int = 1
    started_at: datetime | None = None
    finished_at: datetime | None = None
    runtime_seconds: float = 0.0
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    error: str = ""
    software_versions: dict[str, str] = Field(default_factory=dict)
    limitations: str = ""
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION


# --------------------------------------------------------------------------
# Quantum experiment
# --------------------------------------------------------------------------
class QuantumEvidence(BaseModel):
    """Self-describing record so a quantum result cannot appear to optimize constraints it
    did not encode (review finding #13). Resource/cardinality constraints listed under
    ``unencoded_constraints`` are enforced ONLY by deterministic post-verification."""

    model_config = ConfigDict(frozen=True)

    problem_checksum: str
    qubo_checksum: str
    variable_mapping: tuple[str, ...]  # qubit index i -> opportunity id
    qubit_to_variable: dict[int, str]
    bit_order: str
    encoded_constraints: tuple[str, ...]
    unencoded_constraints: tuple[str, ...]
    penalty_value: float
    penalty_source: str
    penalty_sufficient: bool
    penalty_satisfying_assignment_exists: bool
    post_verification_required: bool = True
    simulator_backend: str = "AerSimulator"
    seeds: dict[str, int] = Field(default_factory=dict)
    software_versions: dict[str, str] = Field(default_factory=dict)
    limitations: str = (
        "Only conflict + mandatory constraints are encoded in the QUBO; resource and "
        "cardinality constraints are enforced solely by deterministic post-verification. "
        "Simulator-only; not evidence of hardware advantage."
    )


class QuantumCircuitMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    qubits: int
    depth: int
    gate_counts: dict[str, int]
    shots: int
    optimizer_iterations: int
    qaoa_layers: int
    simulator_backend: str
    transpile_level: int
    seed_simulator: int
    seed_transpiler: int
    best_parameters: dict[str, float] = Field(default_factory=dict)


class QuantumSampleResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    bitstring: str
    count: int
    probability: float
    feasible: bool
    raw_mission_value: float
    objective_value: float
    qubo_energy: float
    violations_count: int


class QuantumExperiment(BaseModel):
    id: str = Field(default_factory=new_id)
    problem_checksum: str
    status: ExperimentStatus
    configuration: SolverConfiguration
    circuit_metadata: QuantumCircuitMetadata | None = None
    evidence: QuantumEvidence | None = None
    total_shots: int = 0
    distinct_samples: int = 0
    feasible_sample_ratio: float = 0.0
    best_feasible_sample: QuantumSampleResult | None = None
    best_infeasible_sample: QuantumSampleResult | None = None
    exact_optimum_in_samples: bool | None = None
    objective_gap: float | None = None
    selected_schedule: CandidateSchedule | None = None
    selected_evaluation: ScheduleEvaluation | None = None
    samples: list[QuantumSampleResult] = Field(default_factory=list)
    seed: int = 1
    runtime_seconds: float = 0.0
    error: str = ""
    software_versions: dict[str, str] = Field(default_factory=dict)
    limitations: str = (
        "Simulator-only (Aer). Subject to shot noise and optimizer variability; "
        "does not demonstrate hardware advantage and must not drive a production mission."
    )
    epistemic_status: EpistemicStatus = EpistemicStatus.HYPOTHESIS
    created_at: datetime = Field(default_factory=utcnow)


# --------------------------------------------------------------------------
# Benchmark + comparison
# --------------------------------------------------------------------------
class BenchmarkThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Quantum is "competitive" only if feasible AND within this relative gap of the
    # exact optimum (e.g. 0.0 == matches optimum). NOT a claim of advantage.
    competitive_relative_gap: float = Field(default=0.0, ge=0.0, le=1.0)
    min_feasible_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)


class BenchmarkComparison(BaseModel):
    id: str = Field(default_factory=new_id)
    problem_checksum: str
    exact_result_id: str | None = None
    greedy_result_id: str | None = None
    quantum_experiment_id: str | None = None
    exact_objective: float | None = None
    greedy_objective: float | None = None
    quantum_objective: float | None = None
    known_optimum: float | None = None
    conclusion: ComparisonConclusion
    thresholds: BenchmarkThresholds = Field(default_factory=BenchmarkThresholds)
    rationale: str = ""
    limitations: str = (
        "Bounded simulator benchmark on a tiny fixture instance. 'quantum-competitive' "
        "means a defined threshold was met for THIS instance, never general advantage."
    )
    epistemic_status: EpistemicStatus = EpistemicStatus.MODEL_ESTIMATE
    created_at: datetime = Field(default_factory=utcnow)


class BenchmarkRun(BaseModel):
    id: str = Field(default_factory=new_id)
    problem_checksum: str
    solver_results: list[SolverResult] = Field(default_factory=list)
    quantum_experiment: QuantumExperiment | None = None
    comparison: BenchmarkComparison | None = None
    artifacts: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
