"""FastAPI application factory.

Builds the app, wires the container via lifespan, registers routers and safe
exception handlers. ``app`` (module-level) is the ASGI target for uvicorn:

    uvicorn orbitmind.api.app:app
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from orbitmind import __version__
from orbitmind.api.container import AppContainer
from orbitmind.api.errors import register_exception_handlers
from orbitmind.api.routers.memory import router as memory_router
from orbitmind.api.routers.missions import router as missions_router
from orbitmind.api.routers.observation_geometry import router as observation_geometry_router
from orbitmind.api.routers.observation_planning import router as observation_planning_router
from orbitmind.api.routers.observation_studies import router as observation_studies_router
from orbitmind.api.routers.optimization import router as optimization_router
from orbitmind.api.routers.small_bodies import router as small_bodies_router
from orbitmind.api.routers.sources import router as sources_router
from orbitmind.api.routers.space_objects import router as space_objects_router
from orbitmind.api.routers.system import system_router, v1_system_router
from orbitmind.core.logging import configure_logging

API_DESCRIPTION = (
    "OrbitMind Living Q-Core — Phase 0/1 orbital vertical slice. Deterministic SGP4 "
    "propagation from bundled sample TLEs (NOT live data), with verification, "
    "provenance, persistence, and visual artifacts."
)


def create_app(container: AppContainer | None = None) -> FastAPI:
    """Create the FastAPI app, optionally with an injected container (for tests)."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = container or AppContainer()
        configure_logging(level=active.settings.log_level, json_output=active.settings.log_json)
        active.init_storage()
        app.state.container = active
        yield

    app = FastAPI(
        title="OrbitMind Living Q-Core",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(system_router)
    app.include_router(v1_system_router)
    app.include_router(missions_router)
    app.include_router(sources_router)
    app.include_router(space_objects_router)
    app.include_router(small_bodies_router)
    app.include_router(memory_router)
    app.include_router(optimization_router)
    app.include_router(observation_geometry_router)
    app.include_router(observation_planning_router)
    app.include_router(observation_studies_router)
    return app


app = create_app()
