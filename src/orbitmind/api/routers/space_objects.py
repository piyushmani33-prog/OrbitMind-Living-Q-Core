"""Space-object routers: unified, kind-agnostic object retrieval."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orbitmind.api.deps import get_small_body_repository
from orbitmind.api.smallbody_schemas import SpaceObjectListResponse
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import is_valid_uuid
from orbitmind.persistence.smallbody_repository import (
    SqlAlchemySmallBodyRepository,
    StoredSpaceObject,
)

router = APIRouter(prefix="/api/v1/space-objects", tags=["space-objects"])

RepoDep = Annotated[SqlAlchemySmallBodyRepository, Depends(get_small_body_repository)]


@router.get("", response_model=SpaceObjectListResponse)
def list_space_objects(
    repo: RepoDep,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> SpaceObjectListResponse:
    """List stored space objects (most recent first), regardless of kind."""
    return SpaceObjectListResponse(
        total=repo.count_space_objects(),
        limit=limit,
        offset=offset,
        items=repo.list_space_objects(limit, offset),
    )


@router.get("/{object_id}", response_model=StoredSpaceObject)
def get_space_object(object_id: str, repo: RepoDep) -> StoredSpaceObject:
    """Retrieve a stored space object by id."""
    if not is_valid_uuid(object_id):
        raise ValidationError("object id is not a valid identifier")
    obj = repo.get_space_object(object_id)
    if obj is None:
        raise NotFoundError("space object not found")
    return obj
