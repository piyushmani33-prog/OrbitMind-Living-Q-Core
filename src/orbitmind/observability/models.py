"""Capability and health reporting models."""

from __future__ import annotations

from pydantic import BaseModel


class CapabilityRecord(BaseModel):
    """A declared platform capability and whether it is currently available."""

    name: str
    available: bool
    detail: str = ""


class HealthReport(BaseModel):
    """Health endpoint payload (no sensitive paths/env, SR-17)."""

    status: str
    version: str
    python_version: str
    database: str  # "connected" | "unavailable"
    execution_mode: str
    quantum: str  # "available" | "unavailable"


class VersionReport(BaseModel):
    """Version endpoint payload."""

    app: str
    version: str
    components: dict[str, str]
