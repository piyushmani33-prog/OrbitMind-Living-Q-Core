"""The API exception handlers translate domain errors to bounded responses (High #3)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from orbitmind.api.errors import register_exception_handlers
from orbitmind.core.errors import ValidationError


class _Model(BaseModel):
    value: int


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/boom-domain")
    def _boom_domain() -> dict[str, str]:
        _Model(value="not-an-int")  # type: ignore[arg-type]  # raises pydantic.ValidationError
        return {}

    @app.get("/boom-orbitmind")
    def _boom_orbitmind() -> dict[str, str]:
        raise ValidationError("bad input")

    @app.get("/boom-unexpected")
    def _boom_unexpected() -> dict[str, str]:
        raise RuntimeError("kaboom")

    return app


def test_domain_pydantic_validation_error_becomes_422() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    resp = client.get("/boom-domain")
    assert resp.status_code == 422
    assert resp.json() == {
        "code": "validation_error",
        "message": "request failed domain validation",
    }


def test_orbitmind_validation_error_becomes_422() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    resp = client.get("/boom-orbitmind")
    assert resp.status_code == 422
    assert resp.json()["code"] == "validation_error"


def test_unexpected_error_stays_500_without_leaking() -> None:
    client = TestClient(_app(), raise_server_exceptions=False)
    resp = client.get("/boom-unexpected")
    assert resp.status_code == 500
    assert resp.json() == {"code": "internal_error", "message": "an internal error occurred"}
    assert "kaboom" not in resp.text  # no internal detail leaked
