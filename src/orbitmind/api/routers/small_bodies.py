"""Small-body routers: lookup, query, close approaches (JPL-backed, guarded)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from orbitmind.api.deps import get_small_body_repository, get_small_body_service
from orbitmind.api.smallbody_schemas import (
    CloseApproachListResponse,
    CloseApproachRequest,
    CloseApproachResponse,
    SmallBodyLookupRequest,
    SmallBodyLookupResponse,
)
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import is_valid_uuid
from orbitmind.persistence.smallbody_repository import (
    SqlAlchemySmallBodyRepository,
    StoredSmallBody,
)
from orbitmind.smallbody.query import SbdbQueryFilter, SmallBodyQueryResultSet
from orbitmind.smallbody.service import SmallBodyService

router = APIRouter(prefix="/api/v1/small-bodies", tags=["small-bodies"])

ServiceDep = Annotated[SmallBodyService, Depends(get_small_body_service)]
RepoDep = Annotated[SqlAlchemySmallBodyRepository, Depends(get_small_body_repository)]


@router.post("/lookup", response_model=SmallBodyLookupResponse)
def lookup_small_body(
    payload: SmallBodyLookupRequest, service: ServiceDep
) -> SmallBodyLookupResponse:
    """Resolve one asteroid/comet by identifier (fixture/cached unless network enabled)."""
    outcome = service.lookup(
        payload.identifier,
        force_refresh=payload.force_refresh,
        generate_artifacts=payload.generate_artifacts,
    )
    return SmallBodyLookupResponse(
        record=outcome.record,
        findings=outcome.findings,
        from_cache=outcome.from_cache,
        artifacts=outcome.artifacts,
    )


@router.post("/query", response_model=SmallBodyQueryResultSet)
def query_small_bodies(
    query_filter: SbdbQueryFilter, service: ServiceDep
) -> SmallBodyQueryResultSet:
    """Constrained SBDB query over asteroids/comets (allowlisted, bounded)."""
    return service.query(query_filter)


@router.post("/close-approaches", response_model=CloseApproachResponse)
def close_approaches(payload: CloseApproachRequest, service: ServiceDep) -> CloseApproachResponse:
    """Query Close-Approach Data (source-reported; close approach is not impact)."""
    outcome = service.close_approaches(
        payload.filter, generate_artifacts=payload.generate_artifacts
    )
    return CloseApproachResponse(
        result=outcome.result, findings=outcome.findings, artifacts=outcome.artifacts
    )


@router.get("/{object_id}", response_model=StoredSmallBody)
def get_small_body(object_id: str, repo: RepoDep) -> StoredSmallBody:
    """Retrieve a stored small body by id."""
    if not is_valid_uuid(object_id):
        raise ValidationError("object id is not a valid identifier")
    body = repo.get_small_body(object_id)
    if body is None:
        raise NotFoundError("small body not found")
    return body


@router.get("/{object_id}/close-approaches", response_model=CloseApproachListResponse)
def get_small_body_close_approaches(object_id: str, repo: RepoDep) -> CloseApproachListResponse:
    """Stored close approaches for a small body (by its designation)."""
    if not is_valid_uuid(object_id):
        raise ValidationError("object id is not a valid identifier")
    body = repo.get_small_body(object_id)
    if body is None:
        raise NotFoundError("small body not found")
    designation = body.designation or body.primary_identifier.identifier
    return CloseApproachListResponse(
        designation=designation,
        approaches=repo.get_close_approaches_for_designation(designation),
    )
