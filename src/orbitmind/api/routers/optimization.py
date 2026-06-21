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
from orbitmind.api.optimization_views import (
    BenchmarkView,
    ProblemView,
    QuantumExperimentView,
    SolverResultView,
)
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import (
    QuantumExperiment,
    SchedulingProblem,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.service import OptimizationService
from orbitmind.optimization.verification import benchmark_verified_for_evidence

router = APIRouter(prefix="/api/v1/optimization", tags=["optimization"])

ServiceDep = Annotated[OptimizationService, Depends(get_optimization_service)]


@router.post("/problems", response_model=ProblemView)
def create_problem(payload: CreateProblemRequest, service: ServiceDep) -> ProblemView:
    """Create a bounded scheduling problem from a bundled fixture or a structured spec."""
    if payload.fixture is not None:
        try:
            problem: SchedulingProblem = fixtures.fixture(payload.fixture)
        except KeyError as exc:
            raise ValidationError(str(exc)) from exc
    else:
        assert payload.problem is not None
        problem = payload.problem.to_domain()  # strict DTO -> server-stamped domain model
    return ProblemView.from_domain(service.create_problem(problem))


@router.get("/problems", response_model=ProblemListResponse)
def list_problems(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProblemListResponse:
    total, items = service.list_problems(limit, offset)
    return ProblemListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[ProblemView.from_domain(p) for p in items],
    )


@router.get("/problems/{problem_id}", response_model=ProblemView)
def get_problem(problem_id: str, service: ServiceDep) -> ProblemView:
    problem = service.get_problem(problem_id)
    if problem is None:
        raise NotFoundError("optimization problem not found")
    return ProblemView.from_domain(problem)


@router.post("/problems/{problem_id}/solve/classical", response_model=SolverResultResponse)
def solve_classical(
    problem_id: str, payload: ClassicalSolveRequest, service: ServiceDep
) -> SolverResultResponse:
    kind = SolverKind.EXACT if payload.solver == "exact" else SolverKind.GREEDY
    result: SolverResult = service.solve_classical(
        problem_id, solver_kind=kind, seed=payload.seed, timeout_seconds=payload.timeout_seconds
    )
    return SolverResultResponse(result=SolverResultView.from_domain(result))


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
    return QuantumExperimentResponse(experiment=QuantumExperimentView.from_domain(experiment))


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
        policy_id=payload.policy_id,
    )
    verified = benchmark_verified_for_evidence(findings)
    return BenchmarkResponse(
        run=BenchmarkView.from_domain(run, verified=verified), findings=findings, verified=verified
    )


@router.get("/runs", response_model=RunListResponse)
def list_runs(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    return RunListResponse(items=service.list_runs(limit, offset))


@router.get("/runs/{run_id}", response_model=SolverResultView | QuantumExperimentView)
def get_run(run_id: str, service: ServiceDep) -> SolverResultView | QuantumExperimentView:
    run = service.get_run(run_id)
    if run is None:
        raise NotFoundError("solver run not found")
    if isinstance(run, SolverResult):
        return SolverResultView.from_domain(run)
    return QuantumExperimentView.from_domain(run)


@router.get("/runs/{run_id}/artifacts", response_model=ArtifactListResponse)
def get_run_artifacts(run_id: str, service: ServiceDep) -> ArtifactListResponse:
    return ArtifactListResponse(scope_id=run_id, artifacts=service.get_artifacts(run_id))
