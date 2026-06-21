"""Centralized exception handlers returning safe error payloads (SR-17)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError

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

    @app.exception_handler(PydanticValidationError)
    async def _handle_domain_validation(
        request: Request, exc: PydanticValidationError
    ) -> JSONResponse:
        # A domain Pydantic model constructed inside a handler/service failed validation
        # (e.g. a malformed datetime that slipped past request validation). Translate to a
        # bounded 422 instead of leaking a 500 (High finding #3). Detail goes to logs only.
        _log.warning("api.domain_validation_error", errors=exc.error_count())
        return JSONResponse(
            status_code=422,
            content=ErrorResponse(
                code="validation_error", message="request failed domain validation"
            ).model_dump(),
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
