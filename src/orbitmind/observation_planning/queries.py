"""Typed owner-scoped query operations for persisted observation planning."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.observation_planning.models import (
    AuthoritativePlanningSolver,
    ObservationPlanningRequest,
    ObservationPlanningResult,
    ObservationPlanningScientificIdentity,
    ObservationPlanningSourceMode,
    PlanningOptimalityLabel,
    PlanningResultStatus,
    PlanningVerificationLabel,
)
from orbitmind.optimization.models import ExperimentStatus, ScheduleEvaluation
from orbitmind.persistence.observation_planning_models import (
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)
from orbitmind.persistence.observation_planning_repository import (
    SqlAlchemyObservationPlanningRepository,
    StoredObservationPlan,
    StoredObservationPlanningRequest,
    StoredObservationPlanningRun,
    normalize_owner_id,
)

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100


class ObservationPlanningPage[T](BaseModel):
    """Bounded deterministic offset page."""

    model_config = ConfigDict(frozen=True)

    items: tuple[T, ...]
    limit: int
    offset: int
    total: int
    has_next: bool


class ObservationPlanningRequestSummary(BaseModel):
    """Stable application summary for an observation-planning request."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    name: str
    request_checksum: str
    source_mode: ObservationPlanningSourceMode
    created_at: datetime


class ObservationPlanningRequestDetails(BaseModel):
    """Rehydrated request details with checksum authentication applied."""

    model_config = ConfigDict(frozen=True)

    summary: ObservationPlanningRequestSummary
    request: ObservationPlanningRequest


class ObservationPlanningRunSummary(BaseModel):
    """Stable application summary for a persisted planning run."""

    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    problem_checksum: str
    source_mode: ObservationPlanningSourceMode
    status: PlanningResultStatus
    selected_solver: AuthoritativePlanningSolver | None
    solver_execution_status: ExperimentStatus | None
    optimality_label: PlanningOptimalityLabel
    verification_label: PlanningVerificationLabel | None
    feasible: bool
    objective_value: float | None
    created_at: datetime
    completed_at: datetime | None
    plan_id: str | None
    limitations: tuple[str, ...]


class ObservationPlanningRunDetails(BaseModel):
    """Rehydrated run details with scientific-identity authentication applied."""

    model_config = ConfigDict(frozen=True)

    summary: ObservationPlanningRunSummary
    result: ObservationPlanningResult
    scientific_identity_checksum: str


class ObservationPlanSummary(BaseModel):
    """Stable application summary for a persisted verified-feasible plan."""

    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str
    owner_id: str
    problem_checksum: str
    selected_opportunity_count: int
    scientific_identity_checksum: str
    created_at: datetime
    limitations: tuple[str, ...]


class ObservationPlanDetails(BaseModel):
    """Rehydrated plan details with evaluation and identity authentication applied."""

    model_config = ConfigDict(frozen=True)

    summary: ObservationPlanSummary
    selected_opportunity_ids: tuple[str, ...]
    evaluation: ScheduleEvaluation
    scientific_identity: ObservationPlanningScientificIdentity


class ObservationPlanningExecutionDetails(BaseModel):
    """Request, run, and optional plan details for one persisted execution."""

    model_config = ConfigDict(frozen=True)

    request: ObservationPlanningRequestDetails
    run: ObservationPlanningRunDetails
    plan: ObservationPlanDetails | None


def get_observation_planning_request(
    session: Session, *, owner_id: str, request_id: str
) -> ObservationPlanningRequestDetails:
    """Return authenticated request details for an owner-scoped request ID."""

    owner = normalize_owner_id(owner_id)
    row = _request_row(session, owner_id=owner, request_id=request_id)
    if row is None:
        raise NotFoundError("observation-planning request not found")
    repo = SqlAlchemyObservationPlanningRepository(session)
    stored = repo.get_planning_request(request_id, owner_id=owner)
    if stored is None:
        raise NotFoundError("observation-planning request not found")
    return _request_details(row, stored)


def get_observation_planning_run(
    session: Session, *, owner_id: str, run_id: str
) -> ObservationPlanningRunDetails:
    """Return authenticated run details for an owner-scoped run ID."""

    owner = normalize_owner_id(owner_id)
    row = _run_row(session, owner_id=owner, run_id=run_id)
    if row is None:
        raise NotFoundError("observation-planning run not found")
    repo = SqlAlchemyObservationPlanningRepository(session)
    stored = repo.get_planning_run(run_id, owner_id=owner)
    if stored is None:
        raise NotFoundError("observation-planning run not found")
    return _run_details(row, stored)


def get_observation_plan(
    session: Session, *, owner_id: str, plan_id: str
) -> ObservationPlanDetails:
    """Return authenticated plan details for an owner-scoped plan ID."""

    owner = normalize_owner_id(owner_id)
    row = _plan_row(session, owner_id=owner, plan_id=plan_id)
    if row is None:
        raise NotFoundError("observation plan not found")
    repo = SqlAlchemyObservationPlanningRepository(session)
    stored = repo.get_observation_plan(plan_id, owner_id=owner)
    if stored is None:
        raise NotFoundError("observation plan not found")
    run = repo.get_planning_run(stored.run_id, owner_id=owner)
    if run is None:
        raise ValidationError("observation plan references a missing run")
    if run.result.status != PlanningResultStatus.VERIFIED_FEASIBLE:
        raise ValidationError("observation plan references a non-success run")
    return _plan_details(row, stored)


def get_observation_planning_execution(
    session: Session, *, owner_id: str, run_id: str
) -> ObservationPlanningExecutionDetails:
    """Return authenticated request, run, and optional plan details for a run."""

    run = get_observation_planning_run(session, owner_id=owner_id, run_id=run_id)
    request = get_observation_planning_request(
        session, owner_id=owner_id, request_id=run.summary.request_id
    )
    plan = (
        get_observation_plan(session, owner_id=owner_id, plan_id=run.summary.plan_id)
        if run.summary.plan_id is not None
        else None
    )
    return ObservationPlanningExecutionDetails(request=request, run=run, plan=plan)


def list_observation_planning_requests(
    session: Session,
    *,
    owner_id: str,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    source_mode: ObservationPlanningSourceMode | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> ObservationPlanningPage[ObservationPlanningRequestSummary]:
    """List authenticated request summaries for one owner."""

    owner = normalize_owner_id(owner_id)
    limit, offset = _validate_page(limit, offset)
    filters: list[Any] = [ObservationPlanningRequestRow.owner_id == owner]
    if source_mode is not None:
        filters.append(ObservationPlanningRequestRow.source_mode == source_mode.value)
    _apply_created_filters(
        filters, ObservationPlanningRequestRow.created_at, created_from, created_to
    )
    total = _count(session, ObservationPlanningRequestRow, filters)
    rows = (
        session.execute(
            select(ObservationPlanningRequestRow)
            .where(*filters)
            .order_by(
                ObservationPlanningRequestRow.created_at.desc(),
                ObservationPlanningRequestRow.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    repo = SqlAlchemyObservationPlanningRepository(session)
    items = tuple(_request_summary(row, _require_request(repo, row.id, owner)) for row in rows)
    return ObservationPlanningPage(
        items=items,
        limit=limit,
        offset=offset,
        total=total,
        has_next=offset + len(items) < total,
    )


def list_observation_planning_runs(
    session: Session,
    *,
    owner_id: str,
    request_id: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    status: PlanningResultStatus | None = None,
    source_mode: ObservationPlanningSourceMode | None = None,
    authoritative_solver: AuthoritativePlanningSolver | None = None,
    feasible_only: bool = False,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> ObservationPlanningPage[ObservationPlanningRunSummary]:
    """List authenticated run summaries for one owner."""

    owner = normalize_owner_id(owner_id)
    limit, offset = _validate_page(limit, offset)
    filters: list[Any] = [ObservationPlanningRunRow.owner_id == owner]
    if request_id is not None:
        filters.append(ObservationPlanningRunRow.request_id == request_id)
    if status is not None:
        filters.append(ObservationPlanningRunRow.planning_status == status.value)
    if source_mode is not None:
        filters.append(ObservationPlanningRunRow.source_mode == source_mode.value)
    if authoritative_solver is not None:
        filters.append(ObservationPlanningRunRow.authoritative_solver == authoritative_solver.value)
    if feasible_only:
        filters.append(ObservationPlanningRunRow.feasible.is_(True))
    _apply_created_filters(filters, ObservationPlanningRunRow.created_at, created_from, created_to)
    total = _count(session, ObservationPlanningRunRow, filters)
    rows = (
        session.execute(
            select(ObservationPlanningRunRow)
            .where(*filters)
            .order_by(
                ObservationPlanningRunRow.created_at.desc(),
                ObservationPlanningRunRow.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    repo = SqlAlchemyObservationPlanningRepository(session)
    items = tuple(_run_summary(row, _require_run(repo, row.id, owner)) for row in rows)
    return ObservationPlanningPage(
        items=items,
        limit=limit,
        offset=offset,
        total=total,
        has_next=offset + len(items) < total,
    )


def list_observation_plans(
    session: Session,
    *,
    owner_id: str,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    source_mode: ObservationPlanningSourceMode | None = None,
    authoritative_solver: AuthoritativePlanningSolver | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> ObservationPlanningPage[ObservationPlanSummary]:
    """List authenticated successful-plan summaries for one owner."""

    owner = normalize_owner_id(owner_id)
    limit, offset = _validate_page(limit, offset)
    filters: list[Any] = [ObservationPlanRow.owner_id == owner]
    if source_mode is not None:
        filters.append(ObservationPlanningRunRow.source_mode == source_mode.value)
    if authoritative_solver is not None:
        filters.append(ObservationPlanningRunRow.authoritative_solver == authoritative_solver.value)
    _apply_created_filters(filters, ObservationPlanRow.created_at, created_from, created_to)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(ObservationPlanRow)
            .join(
                ObservationPlanningRunRow,
                ObservationPlanningRunRow.id == ObservationPlanRow.run_id,
            )
            .where(*filters)
        )
        or 0
    )
    rows = (
        session.execute(
            select(ObservationPlanRow)
            .join(
                ObservationPlanningRunRow,
                ObservationPlanningRunRow.id == ObservationPlanRow.run_id,
            )
            .where(*filters)
            .order_by(ObservationPlanRow.created_at.desc(), ObservationPlanRow.id.desc())
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    repo = SqlAlchemyObservationPlanningRepository(session)
    items = tuple(_plan_summary(row, _require_plan(repo, row.id, owner)) for row in rows)
    return ObservationPlanningPage(
        items=items,
        limit=limit,
        offset=offset,
        total=total,
        has_next=offset + len(items) < total,
    )


def _request_details(
    row: ObservationPlanningRequestRow,
    stored: StoredObservationPlanningRequest,
) -> ObservationPlanningRequestDetails:
    return ObservationPlanningRequestDetails(
        summary=_request_summary(row, stored),
        request=stored.request,
    )


def _request_summary(
    row: ObservationPlanningRequestRow,
    stored: StoredObservationPlanningRequest,
) -> ObservationPlanningRequestSummary:
    return ObservationPlanningRequestSummary(
        id=stored.id,
        owner_id=stored.owner_id,
        name=stored.request.name,
        request_checksum=stored.request_checksum,
        source_mode=ObservationPlanningSourceMode(stored.source_mode),
        created_at=row.created_at,
    )


def _run_details(
    row: ObservationPlanningRunRow,
    stored: StoredObservationPlanningRun,
) -> ObservationPlanningRunDetails:
    return ObservationPlanningRunDetails(
        summary=_run_summary(row, stored),
        result=stored.result,
        scientific_identity_checksum=stored.scientific_identity_checksum,
    )


def _run_summary(
    row: ObservationPlanningRunRow,
    stored: StoredObservationPlanningRun,
) -> ObservationPlanningRunSummary:
    result = stored.result
    return ObservationPlanningRunSummary(
        id=stored.id,
        request_id=stored.request_id,
        owner_id=stored.owner_id,
        request_checksum=result.request_checksum,
        problem_checksum=result.problem_checksum,
        source_mode=result.source_mode,
        status=result.status,
        selected_solver=result.selected_solver,
        solver_execution_status=result.solver_execution_status,
        optimality_label=result.optimality_label,
        verification_label=result.verification_label,
        feasible=result.feasible,
        objective_value=result.objective_value,
        created_at=row.created_at,
        completed_at=row.completed_at,
        plan_id=stored.plan_id,
        limitations=result.limitations,
    )


def _plan_details(row: ObservationPlanRow, stored: StoredObservationPlan) -> ObservationPlanDetails:
    return ObservationPlanDetails(
        summary=_plan_summary(row, stored),
        selected_opportunity_ids=stored.selected_opportunity_ids,
        evaluation=stored.evaluation,
        scientific_identity=stored.scientific_identity,
    )


def _plan_summary(row: ObservationPlanRow, stored: StoredObservationPlan) -> ObservationPlanSummary:
    return ObservationPlanSummary(
        id=stored.id,
        run_id=stored.run_id,
        owner_id=stored.owner_id,
        problem_checksum=stored.problem_checksum,
        selected_opportunity_count=len(stored.selected_opportunity_ids),
        scientific_identity_checksum=stored.scientific_identity_checksum,
        created_at=row.created_at,
        limitations=stored.limitations,
    )


def _request_row(
    session: Session, *, owner_id: str, request_id: str
) -> ObservationPlanningRequestRow | None:
    return (
        session.execute(
            select(ObservationPlanningRequestRow).where(
                ObservationPlanningRequestRow.owner_id == owner_id,
                ObservationPlanningRequestRow.id == request_id,
            )
        )
        .scalars()
        .first()
    )


def _run_row(session: Session, *, owner_id: str, run_id: str) -> ObservationPlanningRunRow | None:
    return (
        session.execute(
            select(ObservationPlanningRunRow).where(
                ObservationPlanningRunRow.owner_id == owner_id,
                ObservationPlanningRunRow.id == run_id,
            )
        )
        .scalars()
        .first()
    )


def _plan_row(session: Session, *, owner_id: str, plan_id: str) -> ObservationPlanRow | None:
    return (
        session.execute(
            select(ObservationPlanRow).where(
                ObservationPlanRow.owner_id == owner_id,
                ObservationPlanRow.id == plan_id,
            )
        )
        .scalars()
        .first()
    )


def _require_request(
    repo: SqlAlchemyObservationPlanningRepository, request_id: str, owner_id: str
) -> StoredObservationPlanningRequest:
    stored = repo.get_planning_request(request_id, owner_id=owner_id)
    if stored is None:
        raise NotFoundError("observation-planning request not found")
    return stored


def _require_run(
    repo: SqlAlchemyObservationPlanningRepository, run_id: str, owner_id: str
) -> StoredObservationPlanningRun:
    stored = repo.get_planning_run(run_id, owner_id=owner_id)
    if stored is None:
        raise NotFoundError("observation-planning run not found")
    return stored


def _require_plan(
    repo: SqlAlchemyObservationPlanningRepository, plan_id: str, owner_id: str
) -> StoredObservationPlan:
    stored = repo.get_observation_plan(plan_id, owner_id=owner_id)
    if stored is None:
        raise NotFoundError("observation plan not found")
    return stored


def _validate_page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > _MAX_LIMIT:
        raise ValidationError(f"limit must be between 1 and {_MAX_LIMIT}")
    if offset < 0:
        raise ValidationError("offset must be non-negative")
    return limit, offset


def _normalize_time_bound(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return ensure_utc(value)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be timezone-aware") from exc


def _apply_created_filters(
    filters: list[Any],
    column: Any,
    created_from: datetime | None,
    created_to: datetime | None,
) -> None:
    start = _normalize_time_bound(created_from, "created_from")
    end = _normalize_time_bound(created_to, "created_to")
    if start is not None and end is not None and end < start:
        raise ValidationError("created_to must be after or equal to created_from")
    if start is not None:
        filters.append(column >= start)
    if end is not None:
        filters.append(column <= end)


def _count(session: Session, row_type: Any, filters: list[Any]) -> int:
    return int(session.scalar(select(func.count()).select_from(row_type).where(*filters)) or 0)
