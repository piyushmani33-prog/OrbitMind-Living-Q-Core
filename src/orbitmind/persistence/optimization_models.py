"""SQLAlchemy ORM models for bounded scheduling optimization (Phase 4A).

Additive tables. Rich pydantic records are stored as JSON for fidelity, with key columns
promoted for querying. Binary artifacts are never stored here — only metadata + paths.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class OptimizationProblemRow(Base):
    __tablename__ = "optimization_problems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    checksum: Mapped[str] = mapped_column(String(64), index=True)
    num_variables: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(64))
    provenance: Mapped[str] = mapped_column(Text)
    epistemic_status: Mapped[str] = mapped_column(String(32))
    limitations: Mapped[str] = mapped_column(Text)
    problem_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ObservationOpportunityRow(Base):
    __tablename__ = "observation_opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("optimization_problems.id"), index=True)
    opportunity_id: Mapped[str] = mapped_column(String(64), index=True)
    satellite_id: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    mission_value: Mapped[float] = mapped_column(Float)
    duration_seconds: Mapped[float] = mapped_column(Float)
    energy_cost: Mapped[float] = mapped_column(Float)
    storage_cost: Mapped[float] = mapped_column(Float)
    pointing_cost: Mapped[float] = mapped_column(Float)
    priority: Mapped[int] = mapped_column(Integer)


class SchedulingConstraintRow(Base):
    __tablename__ = "scheduling_constraints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    problem_id: Mapped[str] = mapped_column(ForeignKey("optimization_problems.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    detail_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class BenchmarkRunRow(Base):
    __tablename__ = "benchmark_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    problem_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    problem_checksum: Mapped[str] = mapped_column(String(64), index=True)
    conclusion: Mapped[str] = mapped_column(String(32))
    verification_passed: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class SolverRunRow(Base):
    __tablename__ = "solver_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    benchmark_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    problem_checksum: Mapped[str] = mapped_column(String(64), index=True)
    solver_kind: Mapped[str] = mapped_column(String(24), index=True)
    solver_name: Mapped[str] = mapped_column(String(64))
    solver_version: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    optimality_status: Mapped[str] = mapped_column(String(16))
    objective_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    known_optimum: Mapped[float | None] = mapped_column(Float, nullable=True)
    objective_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    feasible: Mapped[bool] = mapped_column(Boolean)
    seed: Mapped[int] = mapped_column(Integer)
    runtime_seconds: Mapped[float] = mapped_column(Float)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    software_versions: Mapped[dict[str, str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class QuantumExperimentRow(Base):
    __tablename__ = "quantum_experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    benchmark_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    problem_checksum: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    qubits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shots: Mapped[int] = mapped_column(Integer)
    optimizer_iterations: Mapped[int] = mapped_column(Integer)
    qaoa_layers: Mapped[int] = mapped_column(Integer)
    total_shots: Mapped[int] = mapped_column(Integer)
    distinct_samples: Mapped[int] = mapped_column(Integer)
    feasible_sample_ratio: Mapped[float] = mapped_column(Float)
    objective_gap: Mapped[float | None] = mapped_column(Float, nullable=True)
    exact_optimum_in_samples: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    seed: Mapped[int] = mapped_column(Integer)
    runtime_seconds: Mapped[float] = mapped_column(Float)
    circuit_metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    experiment_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    software_versions: Mapped[dict[str, str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class QuantumSampleResultRow(Base):
    __tablename__ = "quantum_sample_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("quantum_experiments.id"), index=True)
    bitstring: Mapped[str] = mapped_column(String(32))
    count: Mapped[int] = mapped_column(Integer)
    probability: Mapped[float] = mapped_column(Float)
    feasible: Mapped[bool] = mapped_column(Boolean)
    raw_mission_value: Mapped[float] = mapped_column(Float)
    objective_value: Mapped[float] = mapped_column(Float)
    qubo_energy: Mapped[float] = mapped_column(Float)
    violations_count: Mapped[int] = mapped_column(Integer)


class BenchmarkComparisonRow(Base):
    __tablename__ = "benchmark_comparisons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    benchmark_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    problem_checksum: Mapped[str] = mapped_column(String(64), index=True)
    conclusion: Mapped[str] = mapped_column(String(32))
    exact_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    greedy_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantum_objective: Mapped[float | None] = mapped_column(Float, nullable=True)
    known_optimum: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text)
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    epistemic_status: Mapped[str] = mapped_column(String(32))
    limitations: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class OptimizationArtifactRow(Base):
    __tablename__ = "optimization_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope_id: Mapped[str] = mapped_column(String(36), index=True)
    artifact_type: Mapped[str] = mapped_column(String(48))
    path: Mapped[str] = mapped_column(Text)
    sidecar_path: Mapped[str] = mapped_column(Text)
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
