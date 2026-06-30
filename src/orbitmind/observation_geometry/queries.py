"""Owner-scoped authenticated query operations for persisted observation geometry."""

from __future__ import annotations

import datetime as dt
from typing import TypeVar

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_geometry.models import (
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
)
from orbitmind.persistence.observation_geometry_models import (
    ObservationGeometryRequestRow,
    ObservationGeometryRunRow,
)
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
    normalize_owner_id,
)

_DEFAULT_LIMIT = 25
_MAX_LIMIT = 100
_MAX_IDENTIFIER_LENGTH = 120

PageItemT = TypeVar("PageItemT")


class ObservationGeometryPage[PageItemT](BaseModel):
    """Bounded offset page returned by observation-geometry query operations."""

    model_config = ConfigDict(frozen=True)

    total: int
    limit: int
    offset: int
    has_next: bool
    items: tuple[PageItemT, ...]


class ObservationGeometryRequestSummary(BaseModel):
    """Safe request summary after authenticated snapshot rehydration."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    request_checksum: str
    element_checksum: str
    source_identity_checksum: str
    site: GroundObservationSite
    start: dt.datetime
    end: dt.datetime
    step_seconds: int
    minimum_elevation_deg: float
    created_at: dt.datetime


class ObservationGeometryRequestDetails(BaseModel):
    """Authenticated persisted request detail for application use."""

    model_config = ConfigDict(frozen=True)

    summary: ObservationGeometryRequestSummary
    request: GeometryComputationRequest


class ObservationGeometryRunSummary(BaseModel):
    """Safe completed-run summary after authenticated result rehydration."""

    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    geometry_checksum: str
    element_checksum: str
    source_identity_checksum: str
    sample_count: int
    failed_sample_count: int
    interval_count: int
    computation_version: str
    epistemic_status: EpistemicStatus
    limitations: tuple[str, ...]
    created_at: dt.datetime
    completed_at: dt.datetime


class ObservationGeometryRunDetails(BaseModel):
    """Authenticated persisted completed-run detail for application use."""

    model_config = ConfigDict(frozen=True)

    summary: ObservationGeometryRunSummary
    result: GeometryComputationResult


def get_geometry_request(
    session: Session,
    *,
    owner_id: str,
    request_id: str,
) -> ObservationGeometryRequestDetails:
    """Return an owner-scoped persisted request after checksum authentication."""

    owner = normalize_owner_id(owner_id)
    _require_clean_identifier(request_id, "request_id")
    row = _request_row(session, owner_id=owner, request_id=request_id)
    if row is None:
        raise NotFoundError("observation-geometry request not found")
    stored = SqlAlchemyObservationGeometryRepository(session).get_geometry_request(
        row.id,
        owner_id=owner,
    )
    if stored is None:
        raise NotFoundError("observation-geometry request not found")
    return ObservationGeometryRequestDetails(
        summary=_request_summary(row, stored.request),
        request=stored.request,
    )


def get_geometry_run(
    session: Session,
    *,
    owner_id: str,
    run_id: str,
) -> ObservationGeometryRunDetails:
    """Return an owner-scoped completed run after checksum authentication."""

    owner = normalize_owner_id(owner_id)
    _require_clean_identifier(run_id, "run_id")
    row = _run_row(session, owner_id=owner, run_id=run_id)
    if row is None:
        raise NotFoundError("observation-geometry run not found")
    stored = SqlAlchemyObservationGeometryRepository(session).get_geometry_run(
        row.id,
        owner_id=owner,
    )
    if stored is None:
        raise NotFoundError("observation-geometry run not found")
    return ObservationGeometryRunDetails(
        summary=_run_summary(row, stored.result),
        result=stored.result,
    )


def get_geometry_run_for_request(
    session: Session,
    *,
    owner_id: str,
    request_id: str,
) -> ObservationGeometryRunDetails:
    """Return the completed run for an owner-scoped request."""

    owner = normalize_owner_id(owner_id)
    _require_clean_identifier(request_id, "request_id")
    request_row = _request_row(session, owner_id=owner, request_id=request_id)
    if request_row is None:
        raise NotFoundError("observation-geometry request not found")
    row = _run_row_for_request(session, owner_id=owner, request_id=request_id)
    if row is None:
        raise NotFoundError("observation-geometry run not found")
    stored = SqlAlchemyObservationGeometryRepository(session).get_completed_run_for_request(
        request_id,
        owner_id=owner,
    )
    if stored is None:
        raise NotFoundError("observation-geometry run not found")
    return ObservationGeometryRunDetails(
        summary=_run_summary(row, stored.result),
        result=stored.result,
    )


def list_geometry_requests(
    session: Session,
    *,
    owner_id: str,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    site_id: str | None = None,
    created_from: dt.datetime | None = None,
    created_to: dt.datetime | None = None,
) -> ObservationGeometryPage[ObservationGeometryRequestSummary]:
    """List authenticated owner-scoped request summaries, newest first."""

    owner = normalize_owner_id(owner_id)
    limit, offset = _validate_page(limit, offset)
    if site_id is not None:
        _require_clean_identifier(site_id, "site_id")
    created_from, created_to = _normalize_created_range(created_from, created_to)

    criteria = [ObservationGeometryRequestRow.owner_id == owner]
    if site_id is not None:
        criteria.append(ObservationGeometryRequestRow.site_id == site_id)
    if created_from is not None:
        criteria.append(ObservationGeometryRequestRow.created_at >= created_from)
    if created_to is not None:
        criteria.append(ObservationGeometryRequestRow.created_at <= created_to)

    total = _count(
        session,
        select(func.count()).select_from(ObservationGeometryRequestRow).where(*criteria),
    )
    rows = (
        session.execute(
            select(ObservationGeometryRequestRow)
            .where(*criteria)
            .order_by(
                ObservationGeometryRequestRow.created_at.desc(),
                ObservationGeometryRequestRow.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    repository = SqlAlchemyObservationGeometryRepository(session)
    summaries: list[ObservationGeometryRequestSummary] = []
    for row in rows:
        stored = repository.get_geometry_request(row.id, owner_id=owner)
        if stored is None:
            raise NotFoundError("observation-geometry request not found")
        summaries.append(_request_summary(row, stored.request))
    return ObservationGeometryPage(
        total=total,
        limit=limit,
        offset=offset,
        has_next=offset + len(summaries) < total,
        items=tuple(summaries),
    )


def list_geometry_runs(
    session: Session,
    *,
    owner_id: str,
    request_id: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
    created_from: dt.datetime | None = None,
    created_to: dt.datetime | None = None,
) -> ObservationGeometryPage[ObservationGeometryRunSummary]:
    """List authenticated owner-scoped completed-run summaries, newest first."""

    owner = normalize_owner_id(owner_id)
    limit, offset = _validate_page(limit, offset)
    if request_id is not None:
        _require_clean_identifier(request_id, "request_id")
        if _request_row(session, owner_id=owner, request_id=request_id) is None:
            raise NotFoundError("observation-geometry request not found")
    created_from, created_to = _normalize_created_range(created_from, created_to)

    criteria = [ObservationGeometryRunRow.owner_id == owner]
    if request_id is not None:
        criteria.append(ObservationGeometryRunRow.request_id == request_id)
    if created_from is not None:
        criteria.append(ObservationGeometryRunRow.created_at >= created_from)
    if created_to is not None:
        criteria.append(ObservationGeometryRunRow.created_at <= created_to)

    total = _count(
        session,
        select(func.count()).select_from(ObservationGeometryRunRow).where(*criteria),
    )
    rows = (
        session.execute(
            select(ObservationGeometryRunRow)
            .where(*criteria)
            .order_by(
                ObservationGeometryRunRow.created_at.desc(),
                ObservationGeometryRunRow.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        .scalars()
        .all()
    )
    repository = SqlAlchemyObservationGeometryRepository(session)
    summaries: list[ObservationGeometryRunSummary] = []
    for row in rows:
        stored = repository.get_geometry_run(row.id, owner_id=owner)
        if stored is None:
            raise NotFoundError("observation-geometry run not found")
        summaries.append(_run_summary(row, stored.result))
    return ObservationGeometryPage(
        total=total,
        limit=limit,
        offset=offset,
        has_next=offset + len(summaries) < total,
        items=tuple(summaries),
    )


def _validate_page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > _MAX_LIMIT:
        raise ValidationError("limit must be between 1 and 100")
    if offset < 0:
        raise ValidationError("offset must be non-negative")
    return limit, offset


def _normalize_created_range(
    created_from: dt.datetime | None,
    created_to: dt.datetime | None,
) -> tuple[dt.datetime | None, dt.datetime | None]:
    start = _normalize_time_bound(created_from, "created_from")
    end = _normalize_time_bound(created_to, "created_to")
    if start is not None and end is not None and end < start:
        raise ValidationError("created_to must be greater than or equal to created_from")
    return start, end


def _normalize_time_bound(value: dt.datetime | None, field_name: str) -> dt.datetime | None:
    if value is None:
        return None
    try:
        return ensure_utc(value)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be timezone-aware") from exc


def _require_clean_identifier(value: str, field_name: str) -> None:
    if not value or value.strip() != value or len(value) > _MAX_IDENTIFIER_LENGTH:
        raise ValidationError(f"{field_name} must be non-empty, bounded, and unpadded")


def _request_row(
    session: Session,
    *,
    owner_id: str,
    request_id: str,
) -> ObservationGeometryRequestRow | None:
    return (
        session.execute(
            select(ObservationGeometryRequestRow).where(
                ObservationGeometryRequestRow.owner_id == owner_id,
                ObservationGeometryRequestRow.id == request_id,
            )
        )
        .scalars()
        .first()
    )


def _run_row(
    session: Session,
    *,
    owner_id: str,
    run_id: str,
) -> ObservationGeometryRunRow | None:
    return (
        session.execute(
            select(ObservationGeometryRunRow).where(
                ObservationGeometryRunRow.owner_id == owner_id,
                ObservationGeometryRunRow.id == run_id,
            )
        )
        .scalars()
        .first()
    )


def _run_row_for_request(
    session: Session,
    *,
    owner_id: str,
    request_id: str,
) -> ObservationGeometryRunRow | None:
    return (
        session.execute(
            select(ObservationGeometryRunRow).where(
                ObservationGeometryRunRow.owner_id == owner_id,
                ObservationGeometryRunRow.request_id == request_id,
            )
        )
        .scalars()
        .first()
    )


def _request_summary(
    row: ObservationGeometryRequestRow,
    request: GeometryComputationRequest,
) -> ObservationGeometryRequestSummary:
    return ObservationGeometryRequestSummary(
        id=row.id,
        owner_id=row.owner_id,
        request_checksum=row.request_checksum,
        element_checksum=row.element_checksum,
        source_identity_checksum=row.source_identity_checksum,
        site=request.site,
        start=request.start,
        end=request.end,
        step_seconds=request.step_seconds,
        minimum_elevation_deg=request.minimum_elevation_deg,
        created_at=row.created_at,
    )


def _run_summary(
    row: ObservationGeometryRunRow,
    result: GeometryComputationResult,
) -> ObservationGeometryRunSummary:
    return ObservationGeometryRunSummary(
        id=row.id,
        request_id=row.request_id,
        owner_id=row.owner_id,
        request_checksum=row.request_checksum,
        geometry_checksum=row.geometry_checksum,
        element_checksum=row.element_checksum,
        source_identity_checksum=row.source_identity_checksum,
        sample_count=result.sample_count,
        failed_sample_count=result.failed_sample_count,
        interval_count=len(result.intervals),
        computation_version=result.computation_version,
        epistemic_status=result.epistemic_status,
        limitations=result.limitations,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _count(session: Session, statement: Select[tuple[int]]) -> int:
    return int(session.scalar(statement) or 0)
