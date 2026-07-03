"""Read-only API routes for provenance study graph projections."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from orbitmind.api.deps import get_current_owner_id, get_observation_study_session
from orbitmind.api.provenance_graph_schemas import ObservationStudyProvenanceGraphResponse
from orbitmind.core.errors import ValidationError
from orbitmind.observation_studies import get_geometry_planning_study_chain

router = APIRouter(prefix="/api/v1/provenance-graphs", tags=["provenance-graphs"])

SessionDep = Annotated[Session, Depends(get_observation_study_session)]
OwnerDep = Annotated[str, Depends(get_current_owner_id)]

_ALLOWED_CHAIN_QUERY_PARAMS = frozenset({"geometry_run_id", "provenance_link_id"})
_MAX_IDENTIFIER_LENGTH = 120


@router.get(
    "/observation-study/geometry-planning-chain",
    response_model=ObservationStudyProvenanceGraphResponse,
)
def get_observation_study_geometry_planning_chain_graph(
    request: Request,
    session: SessionDep,
    owner_id: OwnerDep,
    geometry_run_id: Annotated[str, Query()],
    provenance_link_id: Annotated[str, Query()],
) -> ObservationStudyProvenanceGraphResponse:
    """Return a deterministic graph projection over an authenticated study chain."""

    _reject_unknown_query_params(request, _ALLOWED_CHAIN_QUERY_PARAMS)
    _require_clean_identifier(geometry_run_id, "geometry_run_id")
    _require_clean_identifier(provenance_link_id, "provenance_link_id")
    chain = get_geometry_planning_study_chain(
        session=session,
        owner_id=owner_id,
        geometry_run_id=geometry_run_id,
        provenance_link_id=provenance_link_id,
    )
    return ObservationStudyProvenanceGraphResponse.from_chain(chain)


def _reject_unknown_query_params(request: Request, allowed_params: frozenset[str]) -> None:
    unexpected = set(request.query_params) - allowed_params
    if unexpected:
        raise ValidationError("unsupported provenance-graph query parameter")


def _require_clean_identifier(value: str, field_name: str) -> None:
    if (
        not value
        or value.strip() != value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(char in value for char in "\r\n\t")
    ):
        raise ValidationError(f"{field_name} must be non-empty, bounded, and unpadded")
