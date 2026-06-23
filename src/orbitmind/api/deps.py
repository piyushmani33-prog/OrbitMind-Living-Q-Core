"""FastAPI dependency providers (read from the app container)."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request

from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.memory.service import MemoryService
from orbitmind.observability.service import ObservabilityService
from orbitmind.optimization.service import OptimizationService
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.smallbody_repository import SqlAlchemySmallBodyRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.smallbody.service import SmallBodyService


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


def get_source_repository(request: Request) -> Iterator[SqlAlchemySourceRepository]:
    """Yield a source repository bound to a per-request session, closed afterwards."""
    container = get_container(request)
    session = container.database.session()
    try:
        yield SqlAlchemySourceRepository(session)
    finally:
        session.close()


def get_small_body_service(request: Request) -> SmallBodyService:
    return get_container(request).small_body_service


def get_small_body_repository(request: Request) -> Iterator[SqlAlchemySmallBodyRepository]:
    """Yield a small-body repository bound to a per-request session."""
    container = get_container(request)
    session = container.database.session()
    try:
        yield SqlAlchemySmallBodyRepository(session)
    finally:
        session.close()


def get_memory_service(request: Request) -> MemoryService:
    return get_container(request).memory_service


def get_optimization_service(request: Request) -> OptimizationService:
    return get_container(request).optimization_service


def get_memory_repository(request: Request) -> Iterator[SqlAlchemyMemoryRepository]:
    """Yield a memory repository bound to a per-request session."""
    container = get_container(request)
    session = container.database.session()
    try:
        yield SqlAlchemyMemoryRepository(session)
    finally:
        session.close()
