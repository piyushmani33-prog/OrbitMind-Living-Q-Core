"""Bounded scheduling-optimization routers (classical + simulator-only quantum)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orbitmind.api.deps import get_memory_service, get_optimization_service
from orbitmind.api.optimization_schemas import (
    ArtifactListResponse,
    BenchmarkEvidenceGraphResponse,
    BenchmarkReadResponse,
    BenchmarkRequest,
    BenchmarkResponse,
    ClassicalSolveRequest,
    CreateProblemRequest,
    EvidenceEdgeView,
    ProblemListResponse,
    QuantumExperimentResponse,
    QuantumSolveRequest,
    RunListResponse,
    SolverResultResponse,
)
from orbitmind.api.optimization_views import (
    ArtifactView,
    BenchmarkView,
    ProblemView,
    QuantumExperimentView,
    RunSummaryView,
    SolverResultView,
)
from orbitmind.core.errors import (
    EvidenceNotAuthenticatedError,
    NotFoundError,
    ValidationError,
)
from orbitmind.memory.service import MemoryService
from orbitmind.optimization import fixtures
from orbitmind.optimization.models import (
    QuantumExperiment,
    SchedulingProblem,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.service import AuthenticatedBenchmark, OptimizationService
from orbitmind.optimization.verification import benchmark_verified_for_evidence


def _summary(auth: AuthenticatedBenchmark) -> RunSummaryView:
    run = auth.run
    if run is None:
        # Malformed persisted evidence: render a bounded integrity-failed summary from the safe
        # denormalized row scalars, never trusting the malformed payload (fifth review, High #2).
        return RunSummaryView(
            id=auth.benchmark_id or "",
            problem_checksum=auth.problem_checksum or "",
            verified=False,
            integrity_failed=True,
            conclusion=None,
            created_at=auth.created_at_iso or "",
            has_quantum=auth.has_quantum,
            receipt_status=auth.receipt_status,
            artifact_count=auth.artifact_count,
        )
    return RunSummaryView(
        id=run.id,
        problem_checksum=run.problem_checksum,
        verified=auth.authenticated,
        integrity_failed=auth.integrity_failed,
        conclusion=auth.safe_conclusion(),
        created_at=run.created_at.isoformat(),
        has_quantum=run.quantum_experiment is not None,
        receipt_status=auth.receipt_status,
        artifact_count=len(run.artifacts),
    )


router = APIRouter(prefix="/api/v1/optimization", tags=["optimization"])

ServiceDep = Annotated[OptimizationService, Depends(get_optimization_service)]
MemoryDep = Annotated[MemoryService, Depends(get_memory_service)]


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
    # Benchmark-level summaries; each is RE-AUTHENTICATED before being labelled verified.
    return RunListResponse(items=[_summary(a) for a in service.list_run_summaries(limit, offset)])


@router.get("/benchmarks/{benchmark_id}", response_model=BenchmarkReadResponse)
def get_benchmark(benchmark_id: str, service: ServiceDep) -> BenchmarkReadResponse:
    """Read persisted benchmark evidence with full re-authentication (Critical #2)."""
    auth = service.read_benchmark_evidence(benchmark_id)
    if not auth.found:
        raise NotFoundError("benchmark not found")
    if auth.run is None:
        # Malformed persisted evidence: bounded integrity error, never a positive serve or a 500.
        raise ValidationError(
            f"benchmark evidence failed integrity reconstruction ({auth.integrity_status})"
        )
    view = BenchmarkView.from_domain(auth.run, verified=auth.authenticated)
    # Never present a positive conclusion for evidence that failed re-authentication.
    safe = view.model_copy(update={"conclusion": auth.safe_conclusion()})
    return BenchmarkReadResponse(
        run=safe, verified=auth.authenticated, integrity_failed=auth.integrity_failed
    )


@router.get(
    "/benchmarks/{benchmark_id}/evidence-graph", response_model=BenchmarkEvidenceGraphResponse
)
def get_benchmark_evidence_graph(
    benchmark_id: str, service: ServiceDep, memory: MemoryDep
) -> BenchmarkEvidenceGraphResponse:
    """Navigate the benchmark's memory edges, RE-AUTHENTICATING the benchmark first (fourth
    review, finding #30). If re-auth fails, the edges are marked integrity_failed and not treated
    as valid evidence; the integrity audit is written by the read and the edge/audit history is
    retained (never deleted)."""
    auth = service.read_benchmark_evidence(benchmark_id)
    if not auth.found:
        raise NotFoundError("benchmark not found")
    if auth.run is None or auth.run.problem_id is None:
        # Malformed persisted evidence: no edges are treated as valid; bounded integrity response.
        return BenchmarkEvidenceGraphResponse(
            benchmark_id=benchmark_id, integrity_failed=True, valid_evidence=False, edges=[]
        )
    result = memory.graph_neighbors(auth.run.problem_id, depth=1, limit=200)
    edges = [
        EvidenceEdgeView(
            edge_kind=n.edge_kind.value,
            direction=n.direction,
            entity_kind=n.entity.kind.value,
            entity_id=n.entity.entity_id,
            integrity_failed=auth.integrity_failed,
        )
        for n in result.neighbors
    ]
    return BenchmarkEvidenceGraphResponse(
        benchmark_id=benchmark_id,
        integrity_failed=auth.integrity_failed,
        valid_evidence=auth.authenticated and not auth.integrity_failed,
        edges=edges,
    )


@router.get("/runs/{run_id}/artifacts", response_model=ArtifactListResponse)
def get_run_artifacts(run_id: str, service: ServiceDep) -> ArtifactListResponse:
    # The scope id is the benchmark id; re-authenticate before serving artifact metadata.
    auth = service.read_benchmark_evidence(run_id)
    if not auth.found:
        raise NotFoundError("benchmark not found")
    if auth.integrity_failed:
        # Tampered / malformed persisted evidence: bounded integrity error (422).
        raise ValidationError("benchmark evidence failed re-authentication; artifacts withheld")
    if not auth.authenticated:
        # Unaccepted / no-signer / failed-receipt: diagnostic only, NOT public evidence (409).
        raise EvidenceNotAuthenticatedError(
            "benchmark evidence is not authenticated; artifacts are diagnostic only"
        )
    artifacts = [ArtifactView(**a) for a in service.get_artifacts(run_id)]
    return ArtifactListResponse(scope_id=run_id, artifacts=artifacts)
