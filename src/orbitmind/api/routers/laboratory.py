"""Laboratory catalog: read-only API and the visual Laboratory Workbench.

Every response is a deterministic projection of the in-process laboratory
registry plus clearly-labelled static architectural metadata. There is no
write, activation, execution, agent or provider route — and none may be added
here without a reviewed architecture change.
"""

from __future__ import annotations

from importlib import resources
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, Response

from orbitmind import __version__
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container
from orbitmind.api.presentation.laboratory import render_laboratory_page
from orbitmind.laboratory.catalog import LaboratoryCatalogProjection, build_catalog_projection
from orbitmind.laboratory.contracts import LaboratoryManifest
from orbitmind.laboratory.registry import UnknownLaboratoryError

router = APIRouter(tags=["laboratory"])

ContainerDep = Annotated[AppContainer, Depends(get_container)]

LABORATORY_PAGE_PATH = "/workbench/laboratory"
_MAX_LABORATORY_ID_LENGTH = 64


@router.get("/api/v1/laboratories", response_model=LaboratoryCatalogProjection)
def list_laboratories(container: ContainerDep) -> LaboratoryCatalogProjection:
    """Deterministic laboratory catalog (registered + clearly-labelled planned)."""
    return build_catalog_projection(container.laboratory_registry)


@router.get("/api/v1/laboratories/{laboratory_id}", response_model=LaboratoryManifest)
def get_laboratory(laboratory_id: str, container: ContainerDep) -> LaboratoryManifest:
    """One registered laboratory manifest; unknown identifiers are a safe 404."""
    if len(laboratory_id) > _MAX_LABORATORY_ID_LENGTH:
        raise UnknownLaboratoryError("laboratory not found")
    return container.laboratory_registry.get(laboratory_id)


@router.get(LABORATORY_PAGE_PATH, response_class=HTMLResponse)
def laboratory_workbench(container: ContainerDep) -> HTMLResponse:
    """Render the read-only Laboratory Workbench from the registry projection."""
    projection = build_catalog_projection(container.laboratory_registry)
    return HTMLResponse(render_laboratory_page(projection, version=__version__))


@router.get("/assets/laboratory.js", include_in_schema=False)
def laboratory_controller_asset() -> Response:
    """Serve the one reviewed laboratory controller asset from package resources."""
    try:
        script = (
            resources.files("orbitmind.api.assets")
            .joinpath("laboratory.js")
            .read_text(encoding="utf-8")
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        return Response(
            "Laboratory controller asset unavailable.",
            status_code=500,
            media_type="text/plain; charset=utf-8",
            headers={"X-Content-Type-Options": "nosniff"},
        )
    return Response(
        script,
        media_type="application/javascript; charset=utf-8",
        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )
