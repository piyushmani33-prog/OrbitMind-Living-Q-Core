"""System routers: health, version, capabilities."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from orbitmind.api.deps import get_observability
from orbitmind.observability.models import CapabilityRecord, HealthReport, VersionReport
from orbitmind.observability.service import ObservabilityService

# Unversioned operational endpoints.
system_router = APIRouter(tags=["system"])
# Versioned capability endpoint.
v1_system_router = APIRouter(prefix="/api/v1/system", tags=["system"])

ObservabilityDep = Annotated[ObservabilityService, Depends(get_observability)]


@system_router.get("/health", response_model=HealthReport)
def health(observability: ObservabilityDep) -> HealthReport:
    """Liveness/readiness: app status, version, Python, DB, mode, quantum."""
    return observability.health()


@system_router.get("/version", response_model=VersionReport)
def version(observability: ObservabilityDep) -> VersionReport:
    """Application and key component versions."""
    return observability.version()


@v1_system_router.get("/capabilities", response_model=list[CapabilityRecord])
def capabilities(observability: ObservabilityDep) -> list[CapabilityRecord]:
    """Declared platform capabilities and their current availability."""
    return observability.capabilities()
