"""FastAPI application factory.

Builds the app, wires the container via lifespan, registers routers and safe
exception handlers. ``app`` (module-level) is the ASGI target for uvicorn:

    uvicorn orbitmind.api.app:app
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.responses import Response

from orbitmind import __version__
from orbitmind.api.container import AppContainer
from orbitmind.api.errors import register_exception_handlers
from orbitmind.api.routers.camera_media import router as camera_media_router
from orbitmind.api.routers.map_orbit_contexts import router as map_orbit_contexts_router
from orbitmind.api.routers.memory import router as memory_router
from orbitmind.api.routers.missions import router as missions_router
from orbitmind.api.routers.observation_geometry import router as observation_geometry_router
from orbitmind.api.routers.observation_planning import router as observation_planning_router
from orbitmind.api.routers.observation_studies import router as observation_studies_router
from orbitmind.api.routers.optimization import router as optimization_router
from orbitmind.api.routers.product_summaries import router as product_summaries_router
from orbitmind.api.routers.provenance_graphs import router as provenance_graphs_router
from orbitmind.api.routers.review import router as review_router
from orbitmind.api.routers.small_bodies import router as small_bodies_router
from orbitmind.api.routers.sources import router as sources_router
from orbitmind.api.routers.space_objects import router as space_objects_router
from orbitmind.api.routers.static_reports import router as static_reports_router
from orbitmind.api.routers.system import system_router, v1_system_router
from orbitmind.api.routers.visual_manifests import router as visual_manifests_router
from orbitmind.api.routers.workbench import router as workbench_router
from orbitmind.core.logging import configure_logging

API_DESCRIPTION = (
    "OrbitMind Living Q-Core — Phase 0/1 orbital vertical slice. Deterministic SGP4 "
    "propagation from bundled sample TLEs (NOT live data), with verification, "
    "provenance, persistence, and visual artifacts."
)
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'none'; "
    "connect-src 'none'; "
    "object-src 'none'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "worker-src 'none'; "
    "media-src 'none'; "
    "manifest-src 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": (
        "geolocation=(), microphone=(), camera=(), payment=(), usb=(), "
        "magnetometer=(), gyroscope=(), accelerometer=()"
    ),
}
WORKBENCH_REFERRER_POLICY = "same-origin"
CAMERA_MEDIA_API_PREFIX = "/workbench/camera/api/"


def create_app(container: AppContainer | None = None) -> FastAPI:
    """Create the FastAPI app with the container's explicit lifecycle ownership."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active = AppContainer() if container is None else container
        active_is_application_owned = not active.caller_owns_lifecycle
        configure_logging(level=active.settings.log_level, json_output=active.settings.log_json)
        active.init_storage()
        app.state.container = active
        try:
            yield
        finally:
            if active_is_application_owned:
                active.shutdown()

    app = FastAPI(
        title="OrbitMind Living Q-Core",
        version=__version__,
        description=API_DESCRIPTION,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def add_browser_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        request_path = request.scope.get("path")
        content_type = (
            response.headers.get("content-type", "").split(";", maxsplit=1)[0].strip().lower()
        )
        if content_type == "text/html":
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
            if request_path == "/workbench" or (
                isinstance(request_path, str) and request_path.startswith("/workbench/")
            ):
                response.headers["Referrer-Policy"] = WORKBENCH_REFERRER_POLICY
        if isinstance(request_path, str) and request_path.startswith(CAMERA_MEDIA_API_PREFIX):
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
            response.headers["Cache-Control"] = "no-store"
        return response

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
    app.include_router(provenance_graphs_router)
    app.include_router(visual_manifests_router)
    app.include_router(static_reports_router)
    app.include_router(map_orbit_contexts_router)
    app.include_router(product_summaries_router)
    app.include_router(review_router)
    app.include_router(camera_media_router)
    app.include_router(workbench_router)
    return app


app = create_app()
