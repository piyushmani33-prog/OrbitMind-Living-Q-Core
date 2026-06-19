"""FastAPI dependency providers (read from the app container)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.observability.service import ObservabilityService
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container


def get_settings_dep(request: Request) -> Settings:
    return get_container(request).settings


def get_observability(request: Request) -> ObservabilityService:
    return get_container(request).observability


def get_orchestrator(request: Request) -> PrimeOrchestrator:
    return get_container(request).orchestrator


def get_repository(request: Request) -> Iterator[SqlAlchemyMissionRepository]:
    """Yield a repository bound to a per-request session, closed afterwards."""
    container = get_container(request)
    session = container.database.session()
    try:
        yield SqlAlchemyMissionRepository(session)
    finally:
        session.close()
