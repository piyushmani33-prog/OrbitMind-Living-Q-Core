"""Read-only API routes for authenticated observation study chains."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from orbitmind.api.deps import get_current_owner_id, get_observation_study_session
from orbitmind.api.observation_studies_schemas import ObservationStudyChainResponse
from orbitmind.core.errors import ValidationError
from orbitmind.observation_studies import get_geometry_planning_study_chain

router = APIRouter(prefix="/api/v1/observation-studies", tags=["observation-studies"])

SessionDep = Annotated[Session, Depends(get_observation_study_session)]
OwnerDep = Annotated[str, Depends(get_current_owner_id)]

_ALLOWED_CHAIN_QUERY_PARAMS = frozenset({"geometry_run_id", "provenance_link_id"})
_MAX_IDENTIFIER_LENGTH = 120


@router.get("/geometry-planning-chain", response_model=ObservationStudyChainResponse)
def get_geometry_planning_chain(
    request: Request,
    session: SessionDep,
    owner_id: OwnerDep,
    geometry_run_id: Annotated[str, Query()],
    provenance_link_id: Annotated[str, Query()],
) -> ObservationStudyChainResponse:
    """Return a read-only authenticated geometry-to-planning study chain."""

    _reject_unknown_query_params(request)
    _require_clean_identifier(geometry_run_id, "geometry_run_id")
    _require_clean_identifier(provenance_link_id, "provenance_link_id")
    return ObservationStudyChainResponse.from_chain(
        get_geometry_planning_study_chain(
            session=session,
            owner_id=owner_id,
            geometry_run_id=geometry_run_id,
            provenance_link_id=provenance_link_id,
        )
    )


def _reject_unknown_query_params(request: Request) -> None:
    unexpected = set(request.query_params) - _ALLOWED_CHAIN_QUERY_PARAMS
    if unexpected:
        raise ValidationError("unsupported observation-study query parameter")


def _require_clean_identifier(value: str, field_name: str) -> None:
    if (
        not value
        or value.strip() != value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(char in value for char in "\r\n\t")
    ):
        raise ValidationError(f"{field_name} must be non-empty, bounded, and unpadded")
