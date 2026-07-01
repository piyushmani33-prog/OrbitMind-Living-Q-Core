"""Read-only visual manifest API routes."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from orbitmind.api.deps import get_repository, get_source_repository
from orbitmind.api.visual_manifest_schemas import MissionVisualManifestResponse
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository

router = APIRouter(prefix="/api/v1/visual-manifests", tags=["visual-manifests"])

RepositoryDep = Annotated[SqlAlchemyMissionRepository, Depends(get_repository)]
SourceRepositoryDep = Annotated[SqlAlchemySourceRepository, Depends(get_source_repository)]


@router.get("/mission/{mission_id}", response_model=MissionVisualManifestResponse)
def get_mission_visual_manifest(
    request: Request,
    mission_id: str,
    repo: RepositoryDep,
    source_repo: SourceRepositoryDep,
) -> MissionVisualManifestResponse:
    """Return a DB-only, path-free visual manifest for a mission."""

    _reject_query_params(request)
    _require_clean_uuid(mission_id)
    mission = repo.get_mission(mission_id)
    if mission is None:
        raise NotFoundError("mission not found")
    return MissionVisualManifestResponse.from_mission(
        mission=mission,
        artifacts=repo.get_artifacts(mission_id),
        findings=repo.get_findings(mission_id),
        source_data=source_repo.get_mission_source_data(mission_id),
    )


def _reject_query_params(request: Request) -> None:
    if request.query_params:
        raise ValidationError("unsupported visual-manifest query parameter")


def _require_clean_uuid(value: str) -> None:
    if not value or value.strip() != value or any(char in value for char in "\r\n\t/\\:"):
        raise ValidationError("mission id is not a valid identifier")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValidationError("mission id is not a valid identifier") from exc
    if str(parsed) != value.lower():
        raise ValidationError("mission id is not a valid identifier")
