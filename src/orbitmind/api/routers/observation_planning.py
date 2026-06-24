"""Bounded observation-planning API routes."""

from __future__ import annotations

import datetime as dt
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from orbitmind.api.deps import get_current_owner_id, get_observation_planning_session
from orbitmind.api.observation_planning_schemas import (
    ObservationPlanListResponse,
    ObservationPlanningExecuteRequest,
    ObservationPlanningExecutionDetailsResponse,
    ObservationPlanningExecutionResponse,
    ObservationPlanningRequestListResponse,
    ObservationPlanningRequestResponse,
    ObservationPlanningRequestSummaryResponse,
    ObservationPlanningRunListResponse,
    ObservationPlanningRunSummaryResponse,
    ObservationPlanResponse,
    ObservationPlanSummaryResponse,
)
from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning import (
    AuthoritativePlanningSolver,
    ObservationPlanningSourceMode,
    PlanningResultStatus,
    execute_observation_planning,
    get_observation_plan,
    get_observation_planning_execution,
    get_observation_planning_request,
    list_observation_planning_requests,
    list_observation_planning_runs,
    list_observation_plans,
)

router = APIRouter(prefix="/api/v1/observation-planning", tags=["observation-planning"])

SessionDep = Annotated[Session, Depends(get_observation_planning_session)]
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


@router.post(
    "/executions",
    response_model=ObservationPlanningExecutionResponse,
    status_code=status.HTTP_201_CREATED,
)
def execute_planning(
    payload: ObservationPlanningExecuteRequest,
    response: Response,
    session: SessionDep,
    owner_id: OwnerDep,
) -> ObservationPlanningExecutionResponse:
    """Synchronously create/reuse a bounded observation-planning execution."""

    request = payload.to_domain()
    execution = execute_observation_planning(
        session=session,
        owner_id=owner_id,
        request=request,
        idempotency_key=payload.idempotency_key,
    )
    if not execution.run_created:
        response.status_code = status.HTTP_200_OK
    return ObservationPlanningExecutionResponse.from_execution(execution)


@router.get("/requests", response_model=ObservationPlanningRequestListResponse)
def list_requests(
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
    source_mode: Annotated[ObservationPlanningSourceMode | None, Query()] = None,
    created_from: Annotated[dt.datetime | None, Query(alias="created-from")] = None,
    created_to: Annotated[dt.datetime | None, Query(alias="created-to")] = None,
) -> ObservationPlanningRequestListResponse:
    """List owner-scoped planning requests, newest first."""

    result = list_observation_planning_requests(
        session,
        owner_id=owner_id,
        limit=page.limit,
        offset=page.offset,
        source_mode=source_mode,
        created_from=created_from,
        created_to=created_to,
    )
    return ObservationPlanningRequestListResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        has_next=result.has_next,
        items=tuple(
            ObservationPlanningRequestSummaryResponse.from_summary(item) for item in result.items
        ),
    )


@router.get("/requests/{request_id}", response_model=ObservationPlanningRequestResponse)
def get_request(
    request_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
) -> ObservationPlanningRequestResponse:
    """Return an owner-scoped request after checksum rehydration."""

    return ObservationPlanningRequestResponse.from_details(
        get_observation_planning_request(session, owner_id=owner_id, request_id=request_id)
    )


@router.get("/requests/{request_id}/runs", response_model=ObservationPlanningRunListResponse)
def list_runs_for_request(
    request_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
    status_filter: Annotated[PlanningResultStatus | None, Query(alias="status")] = None,
    source_mode: Annotated[ObservationPlanningSourceMode | None, Query()] = None,
    authoritative_solver: Annotated[AuthoritativePlanningSolver | None, Query()] = None,
    feasible_only: Annotated[bool, Query()] = False,
    created_from: Annotated[dt.datetime | None, Query(alias="created-from")] = None,
    created_to: Annotated[dt.datetime | None, Query(alias="created-to")] = None,
) -> ObservationPlanningRunListResponse:
    """List owner-scoped runs for a request after verifying the request exists."""

    get_observation_planning_request(session, owner_id=owner_id, request_id=request_id)
    result = list_observation_planning_runs(
        session,
        owner_id=owner_id,
        request_id=request_id,
        limit=page.limit,
        offset=page.offset,
        status=status_filter,
        source_mode=source_mode,
        authoritative_solver=authoritative_solver,
        feasible_only=feasible_only,
        created_from=created_from,
        created_to=created_to,
    )
    return ObservationPlanningRunListResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        has_next=result.has_next,
        items=tuple(
            ObservationPlanningRunSummaryResponse.from_summary(item) for item in result.items
        ),
    )


@router.get("/runs/{run_id}", response_model=ObservationPlanningExecutionDetailsResponse)
def get_run_execution(
    run_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
) -> ObservationPlanningExecutionDetailsResponse:
    """Return request + run + optional plan details for an owner-scoped run."""

    return ObservationPlanningExecutionDetailsResponse.from_details(
        get_observation_planning_execution(session, owner_id=owner_id, run_id=run_id)
    )


@router.get("/plans", response_model=ObservationPlanListResponse)
def list_plans(
    session: SessionDep,
    owner_id: OwnerDep,
    page: Annotated[PageParams, Depends(_page_params)],
    source_mode: Annotated[ObservationPlanningSourceMode | None, Query()] = None,
    authoritative_solver: Annotated[AuthoritativePlanningSolver | None, Query()] = None,
    created_from: Annotated[dt.datetime | None, Query(alias="created-from")] = None,
    created_to: Annotated[dt.datetime | None, Query(alias="created-to")] = None,
) -> ObservationPlanListResponse:
    """List owner-scoped verified-feasible plans, newest first."""

    result = list_observation_plans(
        session,
        owner_id=owner_id,
        limit=page.limit,
        offset=page.offset,
        source_mode=source_mode,
        authoritative_solver=authoritative_solver,
        created_from=created_from,
        created_to=created_to,
    )
    return ObservationPlanListResponse(
        total=result.total,
        limit=result.limit,
        offset=result.offset,
        has_next=result.has_next,
        items=tuple(ObservationPlanSummaryResponse.from_summary(item) for item in result.items),
    )


@router.get("/plans/{plan_id}", response_model=ObservationPlanResponse)
def get_plan(
    plan_id: str,
    session: SessionDep,
    owner_id: OwnerDep,
) -> ObservationPlanResponse:
    """Return an owner-scoped verified-feasible plan after integrity checks."""

    return ObservationPlanResponse.from_details(
        get_observation_plan(session, owner_id=owner_id, plan_id=plan_id)
    )
