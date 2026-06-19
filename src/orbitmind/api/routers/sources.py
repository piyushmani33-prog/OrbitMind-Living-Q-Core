"""Source routers: list/describe sources, policy, health, cache, explicit refresh.

These endpoints expose only sanitized metadata (no arbitrary URLs, file paths,
environment values, stack traces, or oversized raw payloads). The refresh endpoint
is LOCAL-DEVELOPMENT-ONLY: authentication is not implemented yet.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container, get_source_repository
from orbitmind.api.schemas import (
    RefreshResultResponse,
    SourceCacheResponse,
    SourceCacheView,
    SourceSummaryResponse,
)
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.errors import NetworkDisabledError, SourceError
from orbitmind.sources.models import (
    SourceDefinition,
    SourceHealth,
    SourceHealthStatus,
    SourcePolicy,
)
from orbitmind.sources.policies import CELESTRAK_SOURCE_ID

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])

ContainerDep = Annotated[AppContainer, Depends(get_container)]
SourceRepositoryDep = Annotated[SqlAlchemySourceRepository, Depends(get_source_repository)]


def _summary(definition: SourceDefinition) -> SourceSummaryResponse:
    return SourceSummaryResponse(
        source_id=definition.source_id,
        name=definition.name,
        kind=definition.kind.value,
        description=definition.description,
        enabled=definition.enabled,
        network_enabled=definition.policy.network_enabled,
    )


def _require_definition(container: AppContainer, source_id: str) -> SourceDefinition:
    definition = container.catalog.get(source_id)
    if definition is None:
        raise NotFoundError("unknown source")
    return definition


@router.get("", response_model=list[SourceSummaryResponse])
def list_sources(container: ContainerDep) -> list[SourceSummaryResponse]:
    """List registered sources and their enabled/network state."""
    return [_summary(d) for d in container.catalog.list()]


@router.get("/{source_id}", response_model=SourceSummaryResponse)
def get_source(source_id: str, container: ContainerDep) -> SourceSummaryResponse:
    """Describe a single source."""
    return _summary(_require_definition(container, source_id))


@router.get("/{source_id}/policy", response_model=SourcePolicy)
def get_source_policy(source_id: str, container: ContainerDep) -> SourcePolicy:
    """Return the source's operational + rights policy (no secrets/paths)."""
    return _require_definition(container, source_id).policy


@router.get("/{source_id}/health", response_model=SourceHealthStatus)
def get_source_health(
    source_id: str, container: ContainerDep, source_repo: SourceRepositoryDep
) -> SourceHealthStatus:
    """Report source health. Never performs a network request."""
    definition = _require_definition(container, source_id)
    if source_id == CELESTRAK_SOURCE_ID and container.celestrak is not None:
        return container.celestrak.health(source_repo)
    return SourceHealthStatus(
        source_id=source_id,
        health=SourceHealth.HEALTHY if definition.enabled else SourceHealth.DISABLED,
        network_enabled=definition.policy.network_enabled,
        source_enabled=definition.enabled,
        detail="offline bundled source" if source_id != CELESTRAK_SOURCE_ID else "no connector",
    )


@router.get("/{source_id}/cache", response_model=SourceCacheResponse)
def get_source_cache(
    source_id: str, container: ContainerDep, source_repo: SourceRepositoryDep
) -> SourceCacheResponse:
    """List sanitized cache-entry metadata for a source."""
    _require_definition(container, source_id)
    entries = [
        SourceCacheView(
            cache_key=c.cache_key,
            source_id=c.source_id,
            url=c.url,
            checksum=c.checksum,
            schema_version=c.schema_version,
            http_status=c.http_status,
            content_type=c.content_type,
            fetched_at=c.fetched_at,
            expires_at=c.expires_at,
            effective_epoch=c.effective_epoch,
            last_success_at=c.last_success_at,
            last_failure_at=c.last_failure_at,
            failure_reason=c.failure_reason,
        )
        for c in source_repo.list_cache_for_source(source_id)
    ]
    return SourceCacheResponse(source_id=source_id, entries=entries)


@router.post("/{source_id}/refresh", response_model=RefreshResultResponse)
def refresh_source(
    source_id: str,
    container: ContainerDep,
    satellite_id: str = Query(..., min_length=1, max_length=9, pattern=r"^\d{1,9}$"),
) -> RefreshResultResponse:
    """Explicitly refresh one record (LOCAL-DEVELOPMENT-ONLY; no auth yet).

    Respects the network configuration and the minimum refresh interval; returns
    whether the result was fetched, served from cache, suppressed, failed, or
    disabled, and records an audit event.
    """
    _require_definition(container, source_id)
    if source_id != CELESTRAK_SOURCE_ID or container.celestrak is None:
        raise ValidationError("refresh is not supported for this source")

    with container.database.session() as session:
        mission_repo = SqlAlchemyMissionRepository(session)
        source_repo = SqlAlchemySourceRepository(session)
        mission_repo.add_audit_event(
            AuditEvent(
                action=AuditAction.SOURCE_ACCESS_REQUESTED,
                detail={"source": source_id, "id": satellite_id, "trigger": "refresh"},
            )
        )
        try:
            result = container.celestrak.get_element_record(
                satellite_id, source_repo, force_refresh=True
            )
            outcome = result.fetch.outcome.value
            freshness: str | None = result.record.freshness.state.value
            message = f"refresh {outcome}"
        except NetworkDisabledError as exc:
            mission_repo.add_audit_event(
                AuditEvent(action=AuditAction.NETWORK_REJECTED, detail={"source": source_id})
            )
            outcome, freshness, message = "disabled", None, exc.message
        except SourceError as exc:
            mission_repo.add_audit_event(
                AuditEvent(
                    action=AuditAction.SOURCE_REQUEST_FAILED,
                    detail={"source": source_id, "reason": exc.message},
                )
            )
            outcome, freshness, message = "failed", None, exc.message
        session.commit()

    return RefreshResultResponse(
        source_id=source_id,
        satellite_id=satellite_id,
        outcome=outcome,
        freshness_state=freshness,
        message=message,
    )
