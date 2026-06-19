"""Mission routers: submit orbit-propagation, retrieve, list, artifacts."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container, get_orchestrator, get_repository
from orbitmind.api.schemas import (
    ArtifactsResponse,
    MissionDetailResponse,
    MissionListResponse,
    MissionSummaryResponse,
    OrbitPropagationRequest,
)
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import is_valid_uuid
from orbitmind.core.units import UNITS
from orbitmind.mission.models import Mission
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.propagation import summarize_samples

router = APIRouter(prefix="/api/v1/missions", tags=["missions"])

OrchestratorDep = Annotated[PrimeOrchestrator, Depends(get_orchestrator)]
RepositoryDep = Annotated[SqlAlchemyMissionRepository, Depends(get_repository)]
ContainerDep = Annotated[AppContainer, Depends(get_container)]


def _to_summary(mission: Mission) -> MissionSummaryResponse:
    return MissionSummaryResponse(
        mission_id=mission.id,
        satellite_id=mission.satellite_id,
        status=mission.status,
        epistemic_status=mission.epistemic_status,
        created_at=mission.created_at,
        completed_at=mission.completed_at,
        request=mission.normalized_request,
    )


def _build_detail(
    mission: Mission,
    repo: SqlAlchemyMissionRepository,
    registry: SourceRegistry,
) -> MissionDetailResponse:
    samples = repo.get_samples(mission.id)
    source = None
    if mission.satellite_id in registry.supported_satellite_ids():
        source = registry.get_source_record(mission.satellite_id)
    return MissionDetailResponse(
        mission_id=mission.id,
        satellite_id=mission.satellite_id,
        status=mission.status,
        epistemic_status=mission.epistemic_status,
        created_at=mission.created_at,
        completed_at=mission.completed_at,
        request=mission.normalized_request,
        source=source,
        units=dict(UNITS),
        summary=summarize_samples(samples),
        sample_count=len(samples),
        samples=samples,
        findings=repo.get_findings(mission.id),
        provenance=repo.get_provenance(mission.id),
        artifacts=repo.get_artifacts(mission.id),
        audit=repo.get_audit_events(mission.id),
    )


@router.post("/orbit-propagation", response_model=MissionDetailResponse, status_code=201)
def submit_orbit_propagation(
    payload: OrbitPropagationRequest,
    orchestrator: OrchestratorDep,
    repo: RepositoryDep,
    container: ContainerDep,
) -> MissionDetailResponse:
    """Submit, validate, run, verify, visualize, persist, and return the mission."""
    request = payload.to_domain()
    mission_id = orchestrator.run_orbit_mission(
        raw_request=payload.model_dump(mode="json"), request=request
    )
    mission = repo.get_mission(mission_id)
    if mission is None:  # pragma: no cover - just persisted
        raise NotFoundError("mission not found after submission")
    return _build_detail(mission, repo, container.registry)


@router.get("", response_model=MissionListResponse)
def list_missions(
    repo: RepositoryDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> MissionListResponse:
    """List stored missions (most recent first)."""
    return MissionListResponse(
        total=repo.count_missions(),
        limit=limit,
        offset=offset,
        items=[_to_summary(m) for m in repo.list_missions(limit, offset)],
    )


@router.get("/{mission_id}", response_model=MissionDetailResponse)
def get_mission(
    mission_id: str,
    repo: RepositoryDep,
    container: ContainerDep,
) -> MissionDetailResponse:
    """Retrieve a stored mission with results, provenance, and audit trail."""
    if not is_valid_uuid(mission_id):
        raise ValidationError("mission id is not a valid identifier")
    mission = repo.get_mission(mission_id)
    if mission is None:
        raise NotFoundError("mission not found")
    return _build_detail(mission, repo, container.registry)


@router.get("/{mission_id}/artifacts", response_model=ArtifactsResponse)
def get_mission_artifacts(
    mission_id: str,
    repo: RepositoryDep,
) -> ArtifactsResponse:
    """List the generated visual artifacts for a mission."""
    if not is_valid_uuid(mission_id):
        raise ValidationError("mission id is not a valid identifier")
    if repo.get_mission(mission_id) is None:
        raise NotFoundError("mission not found")
    return ArtifactsResponse(mission_id=mission_id, artifacts=repo.get_artifacts(mission_id))
