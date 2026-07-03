"""Read-only static report API routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from orbitmind.api.deps import get_optimization_service, get_repository, get_source_repository
from orbitmind.api.optimization_views import ArtifactView
from orbitmind.api.static_report_schemas import (
    MissionStaticReportResponse,
    OptimizationBenchmarkStaticReportResponse,
)
from orbitmind.api.visual_manifest_schemas import (
    MissionVisualManifestResponse,
    OptimizationBenchmarkVisualManifestResponse,
)
from orbitmind.core.errors import EvidenceNotAuthenticatedError, NotFoundError, ValidationError
from orbitmind.optimization.service import OptimizationService
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository

router = APIRouter(prefix="/api/v1/static-reports", tags=["static-reports"])

RepositoryDep = Annotated[SqlAlchemyMissionRepository, Depends(get_repository)]
SourceRepositoryDep = Annotated[SqlAlchemySourceRepository, Depends(get_source_repository)]
OptimizationServiceDep = Annotated[OptimizationService, Depends(get_optimization_service)]


@router.get("/mission/{mission_id}", response_model=MissionStaticReportResponse)
def get_mission_static_report(
    request: Request,
    mission_id: str,
    repo: RepositoryDep,
    source_repo: SourceRepositoryDep,
) -> MissionStaticReportResponse:
    """Return an on-demand, path-free mission static report."""

    _reject_query_params(request)
    _require_clean_uuid(mission_id)
    mission = repo.get_mission(mission_id)
    if mission is None:
        raise NotFoundError("mission not found")
    manifest = MissionVisualManifestResponse.from_mission(
        mission=mission,
        artifacts=repo.get_artifacts(mission_id),
        findings=repo.get_findings(mission_id),
        source_data=source_repo.get_mission_source_data(mission_id),
    )
    return MissionStaticReportResponse.from_manifest(manifest)


@router.get(
    "/optimization-benchmark/{benchmark_id}",
    response_model=OptimizationBenchmarkStaticReportResponse,
)
def get_optimization_benchmark_static_report(
    request: Request,
    benchmark_id: str,
    service: OptimizationServiceDep,
) -> OptimizationBenchmarkStaticReportResponse:
    """Return an on-demand, fail-closed optimization benchmark static report."""

    _reject_query_params(request)
    _require_clean_uuid(benchmark_id, "benchmark id")
    auth = service.read_benchmark_evidence(benchmark_id)
    if not auth.found:
        raise NotFoundError("benchmark not found")
    if auth.run is None or auth.integrity_failed:
        raise ValidationError("benchmark evidence failed re-authentication; report withheld")
    if not auth.authenticated:
        raise EvidenceNotAuthenticatedError(
            "benchmark evidence is not authenticated; report withheld"
        )
    artifacts = [ArtifactView(**artifact) for artifact in service.get_artifacts(benchmark_id)]
    manifest = OptimizationBenchmarkVisualManifestResponse.from_authenticated_benchmark(
        run=auth.run,
        artifacts=artifacts,
        verified=auth.authenticated,
        integrity_failed=auth.integrity_failed,
        receipt_status=auth.receipt_status,
        comparison_conclusion=auth.safe_conclusion(),
    )
    return OptimizationBenchmarkStaticReportResponse.from_manifest(manifest)


def _reject_query_params(request: Request) -> None:
    if request.query_params:
        raise ValidationError("unsupported static-report query parameter")


def _require_clean_uuid(value: str, field_name: str = "mission id") -> None:
    if not value or value.strip() != value or any(char in value for char in "\r\n\t/\\:"):
        raise ValidationError(f"{field_name} is not a valid identifier")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError(f"{field_name} is not a valid identifier") from exc
    if str(parsed) != value.lower():
        raise ValidationError(f"{field_name} is not a valid identifier")
