"""Read-only API routes for persisted observation geometry."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from orbitmind.api.deps import get_current_owner_id, get_observation_geometry_session
from orbitmind.api.observation_geometry_schemas import (
    ObservationGeometryIntervalListResponse,
    ObservationGeometryRequestListResponse,
    ObservationGeometryRequestResponse,
    ObservationGeometryRequestSummaryResponse,
    ObservationGeometryRunListResponse,
    ObservationGeometryRunResponse,
    ObservationGeometryRunSummaryResponse,
    ObservationGeometrySampleListResponse,
)
from orbitmind.core.errors import ValidationError
from orbitmind.observation_geometry.queries import (
    get_geometry_request,
    get_geometry_run,
    list_geometry_intervals,
    list_geometry_requests,
    list_geometry_runs,
    list_geometry_samples,
)

router = APIRouter(prefix="/api/v1/observation-geometry", tags=["observation-geometry"])

SessionDep = Annotated[Session, Depends(get_observation_geometry_session)]
OwnerDep = Annotated[str, Depends(get_current_owner_id)]

_PAGE_INT_RE = re.compile(r"^(0|[1-9][0-9]*)$")


class PageParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    limit: int
    offset: int


def _parse_page_int(value: str, *, field_name: str) -> int:
    if not _PAGE_INT_RE.fullmatch(value):
        raise ValidationError(f"{field_name} must be a non-negative integer")
    return int(value)


def _page_params(
    limit: Annotated[str, Query(description="Page size, 1..100")] = "25",
    offset: Annotated[str, Query(description="Zero-based page offset")] = "0",
) -> PageParams:
    parsed_limit = _parse_page_int(limit, field_name="limit")
    parsed_offset = _parse_page_int(offset, field_name="offset")
    if parsed_limit < 1 or parsed_limit > 100:
        raise ValidationError("limit must be between 1 and 100")
    return PageParams(limit=parsed_limit, offset=parsed_offset)


@router.get("/requests", response_model=ObservationGeometryRequestListResponse)
def list_requests(
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
    site_id: Annotated[str | None, Query()] = None,
    created_from: Annotated[dt.datetime | None, Query(alias="created-from")] = None,
    created_to: Annotated[dt.datetime | None, Query(alias="created-to")] = None,
) -> ObservationGeometryRequestListResponse:
    """List owner-scoped persisted geometry requests, newest first."""

    if site_id is not None:
        _require_clean_identifier(site_id, "site_id")
    result = list_geometry_requests(
        session,
        owner_id=owner_id,
        limit=page.limit,
        offset=page.offset,
        site_id=site_id,
        created_from=created_from,
        created_to=created_to,
    )
    return ObservationGeometryRequestListResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        has_next=result.has_next,
        items=tuple(
            ObservationGeometryRequestSummaryResponse.from_summary(item) for item in result.items
        ),
    )


@router.get("/requests/{request_id}", response_model=ObservationGeometryRequestResponse)
def get_request(
    request_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
) -> ObservationGeometryRequestResponse:
    """Return an owner-scoped geometry request after checksum authentication."""

    _require_clean_identifier(request_id, "request_id")
    return ObservationGeometryRequestResponse.from_details(
        get_geometry_request(session, owner_id=owner_id, request_id=request_id)
    )


@router.get("/runs", response_model=ObservationGeometryRunListResponse)
def list_runs(
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
    request_id: Annotated[str | None, Query()] = None,
    created_from: Annotated[dt.datetime | None, Query(alias="created-from")] = None,
    created_to: Annotated[dt.datetime | None, Query(alias="created-to")] = None,
) -> ObservationGeometryRunListResponse:
    """List owner-scoped completed geometry runs, newest first."""

    if request_id is not None:
        _require_clean_identifier(request_id, "request_id")
    result = list_geometry_runs(
        session,
        owner_id=owner_id,
        request_id=request_id,
        limit=page.limit,
        offset=page.offset,
        created_from=created_from,
        created_to=created_to,
    )
    return ObservationGeometryRunListResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        has_next=result.has_next,
        items=tuple(
            ObservationGeometryRunSummaryResponse.from_summary(item) for item in result.items
        ),
    )


@router.get("/runs/{run_id}", response_model=ObservationGeometryRunResponse)
def get_run(
    run_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
) -> ObservationGeometryRunResponse:
    """Return an owner-scoped completed geometry run after checksum authentication."""

    _require_clean_identifier(run_id, "run_id")
    return ObservationGeometryRunResponse.from_details(
        get_geometry_run(session, owner_id=owner_id, run_id=run_id)
    )


@router.get("/runs/{run_id}/samples", response_model=ObservationGeometrySampleListResponse)
def list_run_samples(
    run_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
) -> ObservationGeometrySampleListResponse:
    """Return authenticated geometry samples for one owner-scoped run."""

    _require_clean_identifier(run_id, "run_id")
    return ObservationGeometrySampleListResponse.from_page(
        list_geometry_samples(
            session,
            owner_id=owner_id,
            run_id=run_id,
            limit=page.limit,
            offset=page.offset,
        )
    )


@router.get("/runs/{run_id}/intervals", response_model=ObservationGeometryIntervalListResponse)
def list_run_intervals(
    run_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
) -> ObservationGeometryIntervalListResponse:
    """Return authenticated visibility intervals for one owner-scoped run."""

    _require_clean_identifier(run_id, "run_id")
    return ObservationGeometryIntervalListResponse.from_page(
        list_geometry_intervals(
            session,
            owner_id=owner_id,
            run_id=run_id,
            limit=page.limit,
            offset=page.offset,
        )
    )


def _require_clean_identifier(value: str, field_name: str) -> None:
    if not value or value.strip() != value or len(value) > 120:
        raise ValidationError(f"{field_name} must be non-empty, bounded, and unpadded")
