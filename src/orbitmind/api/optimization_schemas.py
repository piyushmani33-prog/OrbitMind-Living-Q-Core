"""API wire schemas for bounded scheduling optimization (Phase 4A)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from orbitmind.optimization.models import (
    BenchmarkRun,
    QuantumExperiment,
    SchedulingProblem,
    SolverResult,
)
from orbitmind.verification.models import VerificationFinding

OPTIMIZATION_DISCLAIMER = (
    "Bounded, simulator-only quantum experiment with MANDATORY classical baselines on the "
    "same normalized instance. 'quantum-competitive' means a defined threshold was met for "
    "this tiny fixture, NEVER general quantum advantage. No experimental quantum result "
    "controls a production mission; every schedule is independently re-verified."
)


class CreateProblemRequest(BaseModel):
    """Create a problem from a bundled fixture OR a full structured spec (exactly one)."""

    fixture: str | None = None
    problem: SchedulingProblem | None = None

    @model_validator(mode="after")
    def _check(self) -> CreateProblemRequest:
        if (self.fixture is None) == (self.problem is None):
            raise ValueError("provide exactly one of 'fixture' or 'problem'")
        return self


class ClassicalSolveRequest(BaseModel):
    solver: Literal["exact", "greedy"]
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=60.0)


class QuantumSolveRequest(BaseModel):
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    shots: int = Field(default=2048, ge=1, le=16384)
    optimizer_iterations: int = Field(default=24, ge=1, le=128)
    qaoa_layers: int = Field(default=1, ge=1, le=3)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=60.0)


class BenchmarkRequest(BaseModel):
    seed: int = Field(default=1, ge=0, le=2**31 - 1)
    shots: int = Field(default=2048, ge=1, le=16384)
    optimizer_iterations: int = Field(default=24, ge=1, le=128)
    qaoa_layers: int = Field(default=1, ge=1, le=3)
    timeout_seconds: float = Field(default=30.0, gt=0.0, le=60.0)
    run_quantum: bool = True
    generate_artifacts: bool = False
    competitive_relative_gap: float = Field(default=0.0, ge=0.0, le=1.0)
    min_feasible_sample_ratio: float = Field(default=0.05, ge=0.0, le=1.0)


class ProblemListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[SchedulingProblem]


class SolverResultResponse(BaseModel):
    result: SolverResult
    disclaimer: str = OPTIMIZATION_DISCLAIMER


class QuantumExperimentResponse(BaseModel):
    experiment: QuantumExperiment
    disclaimer: str = OPTIMIZATION_DISCLAIMER


class BenchmarkResponse(BaseModel):
    run: BenchmarkRun
    findings: list[VerificationFinding]
    verified: bool
    disclaimer: str = OPTIMIZATION_DISCLAIMER


class RunListResponse(BaseModel):
    items: list[dict[str, object]]


class ArtifactListResponse(BaseModel):
    scope_id: str
    artifacts: list[dict[str, str]]
    disclaimer: str = OPTIMIZATION_DISCLAIMER


__all__ = [
    "OPTIMIZATION_DISCLAIMER",
    "ArtifactListResponse",
    "BenchmarkRequest",
    "BenchmarkResponse",
    "ClassicalSolveRequest",
    "CreateProblemRequest",
    "ProblemListResponse",
    "QuantumExperimentResponse",
    "QuantumSolveRequest",
    "RunListResponse",
    "SolverResultResponse",
]
