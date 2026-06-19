"""Centralized exception handlers returning safe error payloads (SR-17)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from orbitmind.api.schemas import ErrorResponse
from orbitmind.core.errors import OrbitMindError
from orbitmind.core.logging import get_logger

_log = get_logger("api.errors")


def register_exception_handlers(app: FastAPI) -> None:
    """Attach handlers that convert exceptions to safe JSON responses."""

    @app.exception_handler(OrbitMindError)
    async def _handle_orbitmind_error(request: Request, exc: OrbitMindError) -> JSONResponse:
        # Full detail to logs; only the safe message to the client.
        _log.warning("api.error", code=exc.code, status=exc.http_status, message=exc.message)
        return JSONResponse(
            status_code=exc.http_status,
            content=ErrorResponse(code=exc.code, message=exc.message).model_dump(),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internal detail (stack traces, paths, env) to clients.
        _log.error("api.unexpected_error", error=str(exc))
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                code="internal_error", message="an internal error occurred"
            ).model_dump(),
        )
