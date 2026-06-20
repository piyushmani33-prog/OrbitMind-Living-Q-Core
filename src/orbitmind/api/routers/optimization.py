"""Bounded scheduling-optimization routers (classical + simulator-only quantum)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orbitmind.api.deps import get_optimization_service
from orbitmind.api.optimization_schemas import (
    ArtifactListResponse,
    BenchmarkRequest,
    BenchmarkResponse,
    ClassicalSolveRequest,
    CreateProblemRequest,
    ProblemListResponse,
    QuantumExperimentResponse,
    QuantumSolveRequest,
    RunListResponse,
    SolverResultResponse,
)
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import (
    BenchmarkThresholds,
    QuantumExperiment,
    SchedulingProblem,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.service import OptimizationService

router = APIRouter(prefix="/api/v1/optimization", tags=["optimization"])

ServiceDep = Annotated[OptimizationService, Depends(get_optimization_service)]


@router.post("/problems", response_model=SchedulingProblem)
def create_problem(payload: CreateProblemRequest, service: ServiceDep) -> SchedulingProblem:
    """Create a bounded scheduling problem from a bundled fixture or a structured spec."""
    if payload.fixture is not None:
        try:
            problem: SchedulingProblem = fixtures.fixture(payload.fixture)
        except KeyError as exc:
            raise ValidationError(str(exc)) from exc
    else:
        assert payload.problem is not None
        problem = payload.problem
    return service.create_problem(problem)


@router.get("/problems", response_model=ProblemListResponse)
def list_problems(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProblemListResponse:
    total, items = service.list_problems(limit, offset)
    return ProblemListResponse(total=total, limit=limit, offset=offset, items=items)


@router.get("/problems/{problem_id}", response_model=SchedulingProblem)
def get_problem(problem_id: str, service: ServiceDep) -> SchedulingProblem:
    problem = service.get_problem(problem_id)
    if problem is None:
        raise NotFoundError("optimization problem not found")
    return problem


@router.post("/problems/{problem_id}/solve/classical", response_model=SolverResultResponse)
def solve_classical(
    problem_id: str, payload: ClassicalSolveRequest, service: ServiceDep
) -> SolverResultResponse:
    kind = SolverKind.EXACT if payload.solver == "exact" else SolverKind.GREEDY
    result: SolverResult = service.solve_classical(
        problem_id, solver_kind=kind, seed=payload.seed, timeout_seconds=payload.timeout_seconds
    )
    return SolverResultResponse(result=result)


@router.post("/problems/{problem_id}/solve/quantum", response_model=QuantumExperimentResponse)
def solve_quantum(
    problem_id: str, payload: QuantumSolveRequest, service: ServiceDep
) -> QuantumExperimentResponse:
    """Run a simulator-only QAOA experiment; returns 'unsupported' status if Aer is absent."""
    experiment: QuantumExperiment = service.solve_quantum(
        problem_id,
        seed=payload.seed,
        shots=payload.shots,
        optimizer_iterations=payload.optimizer_iterations,
        qaoa_layers=payload.qaoa_layers,
        timeout_seconds=payload.timeout_seconds,
    )
    return QuantumExperimentResponse(experiment=experiment)


@router.post("/problems/{problem_id}/benchmark", response_model=BenchmarkResponse)
def benchmark(problem_id: str, payload: BenchmarkRequest, service: ServiceDep) -> BenchmarkResponse:
    """Run exact + greedy + (optional) quantum on the same instance, verified + compared."""
    run, findings = service.benchmark(
        problem_id,
        seed=payload.seed,
        shots=payload.shots,
        optimizer_iterations=payload.optimizer_iterations,
        qaoa_layers=payload.qaoa_layers,
        timeout_seconds=payload.timeout_seconds,
        run_quantum=payload.run_quantum,
        generate_artifacts=payload.generate_artifacts,
        thresholds=BenchmarkThresholds(
            competitive_relative_gap=payload.competitive_relative_gap,
            min_feasible_sample_ratio=payload.min_feasible_sample_ratio,
        ),
    )
    verified = all(f.passed for f in findings)
    return BenchmarkResponse(run=run, findings=findings, verified=verified)


@router.get("/runs", response_model=RunListResponse)
def list_runs(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    return RunListResponse(items=service.list_runs(limit, offset))


@router.get("/runs/{run_id}")
def get_run(run_id: str, service: ServiceDep) -> SolverResult | QuantumExperiment:
    run = service.get_run(run_id)
    if run is None:
        raise NotFoundError("solver run not found")
    return run


@router.get("/runs/{run_id}/artifacts", response_model=ArtifactListResponse)
def get_run_artifacts(run_id: str, service: ServiceDep) -> ArtifactListResponse:
    return ArtifactListResponse(scope_id=run_id, artifacts=service.get_artifacts(run_id))
